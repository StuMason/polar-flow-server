"""API key authentication for service-to-service requests."""

import hashlib
import logging
import secrets
from datetime import UTC, datetime
from typing import Any

from litestar.connection import ASGIConnection
from litestar.exceptions import NotAuthorizedException
from litestar.handlers import BaseRouteHandler
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.core.config import settings
from polar_flow_server.models.api_key import APIKey

logger = logging.getLogger(__name__)

# API key prefix for identification
API_KEY_PREFIX = "pfs_"


def generate_api_key() -> tuple[str, str]:
    """Generate a new API key and its hash.

    Returns:
        Tuple of (raw_key, key_hash) where raw_key is the user-facing key
        and key_hash is what gets stored in the database.
    """
    # Generate 32 bytes of random data, encode as hex (64 chars)
    random_part = secrets.token_hex(32)
    raw_key = f"{API_KEY_PREFIX}{random_part}"
    key_hash = hash_api_key(raw_key)
    return raw_key, key_hash


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
    api_key = connection.headers.get("X-API-Key")

    if not api_key:
        # Try Authorization: Bearer header
        auth_header = connection.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            api_key = auth_header[7:]

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
