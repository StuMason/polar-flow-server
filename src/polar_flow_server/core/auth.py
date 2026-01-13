"""API key authentication for service-to-service requests.

Supports two authentication modes:
1. Simple mode: Single API key from config (API_KEY env var)
2. Per-user mode: User-scoped keys from database with rate limiting
"""

import hashlib
import logging
import secrets
from datetime import UTC, datetime
from typing import Any

from litestar.connection import ASGIConnection
from litestar.exceptions import NotAuthorizedException
from litestar.handlers import BaseRouteHandler
from litestar.status_codes import HTTP_429_TOO_MANY_REQUESTS
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.core.config import settings
from polar_flow_server.models.api_key import APIKey

logger = logging.getLogger(__name__)

# Connection state key for storing validated API key
API_KEY_STATE_KEY = "api_key"
RATE_LIMIT_STATE_KEY = "rate_limit_info"


class RateLimitExceeded(NotAuthorizedException):
    """Exception raised when rate limit is exceeded."""

    status_code = HTTP_429_TOO_MANY_REQUESTS

    def __init__(self, retry_after: int) -> None:
        """Initialize with retry-after seconds."""
        super().__init__(f"Rate limit exceeded. Retry after {retry_after} seconds.")
        self.retry_after = retry_after
        self.extra = {"Retry-After": str(retry_after)}


def hash_api_key(key: str) -> str:
    """Hash an API key using SHA-256.

    Args:
        key: The raw API key to hash

    Returns:
        SHA-256 hash of the key as hex string
    """
    return hashlib.sha256(key.encode()).hexdigest()


async def validate_api_key(key: str, session: AsyncSession) -> APIKey | None:
    """Validate an API key against the database.

    Args:
        key: The raw API key to validate
        session: Database session

    Returns:
        The APIKey model if valid, None otherwise
    """
    key_hash = hash_api_key(key)

    result = await session.execute(
        select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active == True)  # noqa: E712
    )
    api_key = result.scalar_one_or_none()

    if api_key:
        # Update last_used_at
        await session.execute(
            update(APIKey).where(APIKey.id == api_key.id).values(last_used_at=datetime.now(UTC))
        )
        await session.commit()

    return api_key


async def validate_simple_api_key(key: str) -> bool:
    """Validate API key against simple config-based key.

    For self-hosted single-key deployments where database lookup
    is overkill. Uses constant-time comparison to prevent timing attacks.

    Args:
        key: The API key to validate

    Returns:
        True if valid, False otherwise
    """
    if not settings.api_key:
        return False

    return secrets.compare_digest(key, settings.api_key)


def _extract_api_key(connection: ASGIConnection[Any, Any, Any, Any]) -> str | None:
    """Extract API key from request headers.

    Args:
        connection: The ASGI connection

    Returns:
        The API key string or None if not found
    """
    # Try X-API-Key header first
    api_key = connection.headers.get("X-API-Key")

    if not api_key:
        # Try Authorization: Bearer header
        auth_header = connection.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            api_key = auth_header[7:]

    return api_key


async def _check_rate_limit(api_key: APIKey, session: AsyncSession) -> tuple[bool, dict[str, int]]:
    """Check and update rate limit for an API key.

    Args:
        api_key: The API key to check
        session: Database session

    Returns:
        Tuple of (is_allowed, rate_limit_info)
    """
    from datetime import timedelta

    now = datetime.now(UTC)

    # Reset if window expired
    if api_key.rate_limit_reset_at is None or now >= api_key.rate_limit_reset_at:
        api_key.rate_limit_remaining = api_key.rate_limit_requests
        api_key.rate_limit_reset_at = now + timedelta(hours=1)

    # Build rate limit info
    reset_timestamp = int(api_key.rate_limit_reset_at.timestamp())
    rate_limit_info = {
        "limit": api_key.rate_limit_requests,
        "remaining": max(0, api_key.rate_limit_remaining),
        "reset": reset_timestamp,
    }

    # Check limit
    if api_key.rate_limit_remaining <= 0:
        return False, rate_limit_info

    # Decrement
    api_key.rate_limit_remaining -= 1
    rate_limit_info["remaining"] = api_key.rate_limit_remaining

    # Persist changes
    await session.commit()

    return True, rate_limit_info


async def api_key_guard(
    connection: ASGIConnection[Any, Any, Any, Any], _: BaseRouteHandler
) -> None:
    """Litestar guard that validates API key from request header.

    If no API_KEY is configured, authentication is skipped (open access).
    Otherwise validates against config or database.

    Args:
        connection: The ASGI connection
        _: The route handler (unused)

    Raises:
        NotAuthorizedException: If API key is required but missing/invalid
    """
    # If no API_KEY configured, skip authentication (simple self-hosted mode)
    if not settings.api_key:
        logger.debug("No API_KEY configured - authentication disabled")
        return

    # Extract API key from headers
    api_key = _extract_api_key(connection)

    if not api_key:
        logger.warning("API request without authentication")
        raise NotAuthorizedException("Missing API key. Use X-API-Key header.")

    # Validate the key
    is_valid = await validate_simple_api_key(api_key)

    # If config key didn't match, try database
    if not is_valid:
        from polar_flow_server.core.database import async_session_maker

        async with async_session_maker() as session:
            api_key_model = await validate_api_key(api_key, session)
            is_valid = api_key_model is not None

    if not is_valid:
        logger.warning("Invalid API key attempted")
        raise NotAuthorizedException("Invalid API key")

    logger.debug("API key validated successfully")


async def per_user_api_key_guard(
    connection: ASGIConnection[Any, Any, Any, Any], _: BaseRouteHandler
) -> None:
    """Litestar guard that validates per-user API keys with rate limiting.

    This guard:
    1. Validates the API key
    2. Checks rate limits
    3. For user-scoped keys, verifies access to the requested user

    Authorization Model:
    - **User-scoped keys** (user_id set): Can ONLY access their own data.
      These are issued to end users via OAuth flow.
    - **Service-level keys** (user_id=None): Can access ANY user's data.
      These are intentionally for admin/backend use (e.g., Laravel SaaS
      backend making requests on behalf of users). Service keys should
      only be issued to trusted backend systems, never to end users.

    Args:
        connection: The ASGI connection
        _: The route handler (unused)

    Raises:
        NotAuthorizedException: If authentication fails
        RateLimitExceeded: If rate limit is exceeded
    """
    # Extract API key from headers
    raw_key = _extract_api_key(connection)

    if not raw_key:
        # Check if simple API key mode is enabled (config-based)
        if settings.api_key:
            raise NotAuthorizedException("Missing API key. Use X-API-Key header.")
        # No API key required in open access mode
        logger.debug("No API_KEY configured - authentication disabled")
        return

    # First check if it matches the config-based master key
    if settings.api_key and secrets.compare_digest(raw_key, settings.api_key):
        logger.debug("Config-based master API key validated")
        return

    # Validate against database
    from polar_flow_server.core.database import async_session_maker

    async with async_session_maker() as session:
        key_hash = hash_api_key(raw_key)

        result = await session.execute(select(APIKey).where(APIKey.key_hash == key_hash))
        api_key = result.scalar_one_or_none()

        if api_key is None or not api_key.is_active:
            logger.warning("Invalid or inactive API key attempted")
            raise NotAuthorizedException("Invalid API key")

        # Check rate limit BEFORE any data access
        is_allowed, rate_limit_info = await _check_rate_limit(api_key, session)

        # Store rate limit info in connection state for response headers
        connection.state[RATE_LIMIT_STATE_KEY] = rate_limit_info

        if not is_allowed:
            retry_after = rate_limit_info["reset"] - int(datetime.now(UTC).timestamp())
            raise RateLimitExceeded(retry_after=max(1, retry_after))

        # Authorization check: user-scoped keys can only access their own data.
        # Service-level keys (user_id=None) intentionally skip this check -
        # they can access any user's data for admin/backend operations.
        path_user_id = connection.path_params.get("user_id")
        if api_key.user_id is not None and path_user_id:
            if api_key.user_id != path_user_id:
                logger.warning(
                    f"API key for user {api_key.user_id} attempted to access user {path_user_id}"
                )
                raise NotAuthorizedException("API key not authorized for this user")

        # Update last_used_at
        api_key.last_used_at = datetime.now(UTC)
        await session.commit()

        # Store API key info in connection state
        connection.state[API_KEY_STATE_KEY] = {
            "id": api_key.id,
            "user_id": api_key.user_id,
            "is_service_level": api_key.user_id is None,
        }

        logger.debug(
            f"API key validated: id={api_key.id}, user_scoped={'yes' if api_key.user_id else 'no'}"
        )


def get_rate_limit_headers(connection: ASGIConnection[Any, Any, Any, Any]) -> dict[str, str]:
    """Get rate limit headers from connection state.

    Args:
        connection: The ASGI connection

    Returns:
        Dict of rate limit headers
    """
    rate_limit_info = connection.state.get(RATE_LIMIT_STATE_KEY)
    if not rate_limit_info:
        return {}

    return {
        "X-RateLimit-Limit": str(rate_limit_info["limit"]),
        "X-RateLimit-Remaining": str(rate_limit_info["remaining"]),
        "X-RateLimit-Reset": str(rate_limit_info["reset"]),
    }
