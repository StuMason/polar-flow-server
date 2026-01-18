"""API key management endpoints.

Provides endpoints for:
- OAuth code exchange (get API key from temp code)
- Key regeneration
- Key revocation
- User status
- SaaS OAuth start (for external clients like Laravel)
"""

import asyncio
import logging
import secrets
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlparse

from litestar import Router, get, post
from litestar.connection import Request
from litestar.exceptions import NotAuthorizedException, NotFoundException
from litestar.params import Parameter
from litestar.response import Redirect
from litestar.status_codes import HTTP_200_OK, HTTP_201_CREATED, HTTP_303_SEE_OTHER
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.core.api_keys import (
    create_api_key_for_user,
    create_temp_auth_code,
    exchange_temp_code,
    regenerate_api_key,
    revoke_api_key,
)
from polar_flow_server.core.auth import per_user_api_key_guard
from polar_flow_server.core.config import settings
from polar_flow_server.models.api_key import APIKey
from polar_flow_server.models.settings import AppSettings
from polar_flow_server.models.user import User

logger = logging.getLogger(__name__)


# =============================================================================
# Bounded TTL Cache for OAuth States (prevents memory exhaustion)
# =============================================================================


class BoundedOAuthStateCache:
    """Bounded cache for SaaS OAuth states with TTL.

    Prevents memory exhaustion attacks by limiting max entries.
    Stores callback_url and client_id along with expiry.
    Thread-safe via asyncio lock.
    """

    def __init__(self, maxsize: int = 100, ttl_minutes: int = 10) -> None:
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._maxsize = maxsize
        self._ttl = timedelta(minutes=ttl_minutes)
        self._lock = asyncio.Lock()

    async def set(self, key: str, callback_url: str, client_id: str | None = None) -> None:
        """Add a new OAuth state with its associated data."""
        async with self._lock:
            self._cleanup_expired()
            # If at max, evict oldest entry and log warning
            if len(self._cache) >= self._maxsize:
                logger.warning(
                    f"SaaS OAuth state cache full ({self._maxsize}), evicting oldest entries"
                )
            while len(self._cache) >= self._maxsize:
                self._cache.popitem(last=False)
            self._cache[key] = {
                "expires_at": datetime.now(UTC) + self._ttl,
                "callback_url": callback_url,
                "client_id": client_id,
            }

    async def get(self, key: str) -> dict[str, Any] | None:
        """Get state data, or None if not found/expired."""
        async with self._lock:
            self._cleanup_expired()
            return self._cache.get(key)

    async def pop(self, key: str) -> dict[str, Any] | None:
        """Remove and return state data."""
        async with self._lock:
            return self._cache.pop(key, None)

    async def contains(self, key: str) -> bool:
        """Check if key exists (async version of __contains__)."""
        async with self._lock:
            self._cleanup_expired()
            return key in self._cache

    def _cleanup_expired(self) -> None:
        """Remove expired entries. Must be called with lock held."""
        now = datetime.now(UTC)
        # Use dict comprehension for atomic update
        self._cache = OrderedDict((k, v) for k, v in self._cache.items() if v["expires_at"] >= now)


# OAuth state storage with bounded size (prevents memory exhaustion)
_saas_oauth_states = BoundedOAuthStateCache(maxsize=100, ttl_minutes=10)


# =============================================================================
# Callback URL Validation
# =============================================================================


def _is_localhost(netloc: str) -> bool:
    """Check if netloc is localhost (with or without port)."""
    # Remove port if present
    host = netloc.split(":")[0].lower()
    return host in {"localhost", "127.0.0.1", "::1", "[::1]"}


def _validate_callback_url(callback_url: str) -> tuple[bool, str]:
    """Validate that callback_url is well-formed and secure.

    Returns (is_valid, error_message).
    """
    # Length check to prevent DoS via extremely long URLs
    if len(callback_url) > 2048:
        return False, "URL too long (max 2048 characters)"

    try:
        parsed = urlparse(callback_url)
    except Exception:
        return False, "Invalid URL format"

    # Must have scheme and netloc
    if not parsed.scheme or not parsed.netloc:
        return False, "URL must include scheme and host (e.g., https://example.com/callback)"

    # Only allow http and https schemes
    if parsed.scheme not in {"http", "https"}:
        return False, "Only http and https schemes are allowed"

    # Production check: use deployment_mode or presence of base_url
    is_production = settings.deployment_mode.value == "saas" or settings.base_url is not None

    if parsed.scheme == "http":
        if is_production:
            return False, "HTTPS required for callback URLs in production"
        # In development, only allow http for actual localhost
        if not _is_localhost(parsed.netloc):
            return False, "HTTP only allowed for localhost in development"

    return True, ""


# ==============================================================================
# Request/Response Models
# ==============================================================================


class OAuthExchangeRequest(BaseModel):
    """Request body for OAuth code exchange."""

    code: str = Field(description="Temporary authorization code from OAuth callback")
    client_id: str | None = Field(default=None, description="Optional client identifier")


class OAuthExchangeResponse(BaseModel):
    """Response from OAuth code exchange."""

    api_key: str = Field(description="The API key (shown once, store securely)")
    polar_user_id: str = Field(description="The Polar user ID this key is scoped to")
    expires_at: None = Field(default=None, description="Key expiration (null = never)")


class KeyInfoResponse(BaseModel):
    """Response with API key information (key itself is masked)."""

    key_prefix: str = Field(description="First 8 characters of the key for identification")
    user_id: str | None = Field(description="User ID if user-scoped, null if service-level")
    is_active: bool = Field(description="Whether the key is currently active")
    rate_limit_requests: int = Field(description="Max requests per hour")
    rate_limit_remaining: int = Field(description="Remaining requests in current window")
    created_at: str = Field(description="When the key was created")
    last_used_at: str | None = Field(description="Last time the key was used")


class KeyRegenerateResponse(BaseModel):
    """Response from key regeneration."""

    api_key: str = Field(description="The new API key (shown once, store securely)")
    message: str = Field(default="Key regenerated successfully. Old key is now invalid.")


class UserStatusResponse(BaseModel):
    """Response with user connection status."""

    polar_user_id: str = Field(description="Polar user ID")
    is_active: bool = Field(description="Whether the connection is active")
    last_synced_at: str | None = Field(description="Last sync timestamp")
    has_api_key: bool = Field(description="Whether user has an API key")
    api_key_prefix: str | None = Field(description="API key prefix if exists")


# ==============================================================================
# SaaS OAuth Start Endpoint (for external clients like Laravel)
# ==============================================================================


def _get_base_url_from_headers(headers: dict[str, str]) -> str:
    """Get base URL from request headers."""
    host = headers.get("host", "localhost:8000")
    scheme = headers.get("x-forwarded-proto", "http")
    return f"{scheme}://{host}"


@get("/oauth/start", status_code=HTTP_303_SEE_OTHER)
async def oauth_start_saas(
    request: Request[Any, Any, Any],
    session: AsyncSession,
    callback_url: str,
    client_id: str | None = None,
) -> Redirect:
    """Start OAuth flow for SaaS clients.

    External clients (like Laravel) call this endpoint to initiate OAuth.
    After the user authorizes, they're redirected back to the callback_url
    with a temporary code that can be exchanged for an API key.

    Query Parameters:
        callback_url: Where to redirect after OAuth (your app's callback endpoint)
        client_id: Optional client identifier for validation during exchange
    """
    # Validate callback URL (includes length check)
    is_valid, error_msg = _validate_callback_url(callback_url)
    if not is_valid:
        raise NotAuthorizedException(f"Invalid callback_url: {error_msg}")

    # Validate client_id length to prevent DoS
    if client_id and len(client_id) > 255:
        raise NotAuthorizedException("client_id too long (max 255 characters)")

    # Get OAuth credentials from database
    stmt = select(AppSettings).where(AppSettings.id == 1)
    result = await session.execute(stmt)
    app_settings = result.scalar_one_or_none()

    if not app_settings or not app_settings.polar_client_id:
        raise NotFoundException("OAuth credentials not configured on server")

    # Generate CSRF state token (BoundedOAuthStateCache handles cleanup and size limits)
    state = secrets.token_urlsafe(32)
    await _saas_oauth_states.set(state, callback_url, client_id)

    # Build authorization URL - extract host/scheme from request headers
    # Coolify/nginx sets x-forwarded-* headers
    scheme = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost:8000")
    base_url = f"{scheme}://{host}"
    redirect_uri = f"{base_url}/oauth/callback"

    params = {
        "client_id": app_settings.polar_client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    auth_url = f"https://flow.polar.com/oauth2/authorization?{urlencode(params)}"

    logger.info(
        f"Starting SaaS OAuth flow, callback_url={callback_url}, redirect_uri={redirect_uri}"
    )

    return Redirect(path=auth_url, status_code=HTTP_303_SEE_OTHER)


@get("/oauth/callback", status_code=HTTP_303_SEE_OTHER)
async def oauth_callback_saas(
    request: Request[Any, Any, Any],
    session: AsyncSession,
    code: str | None = None,
    oauth_state: str | None = Parameter(default=None, query="state"),
    error: str | None = None,
) -> Redirect:
    """Handle OAuth callback for SaaS clients.

    After user authorizes on Polar, Polar redirects here.
    We exchange the code for tokens, create a temp auth code,
    and redirect to the client's callback_url with the temp code.
    """
    import httpx

    from polar_flow_server.core.security import token_encryption

    # Handle errors - try to redirect to callback with error if we have state
    if error or not code:
        if oauth_state:
            state_data = await _saas_oauth_states.pop(oauth_state)
            if state_data:
                callback_url = state_data["callback_url"]
                error_params = urlencode({"error": error or "no_code", "status": "failed"})
                return Redirect(
                    path=f"{callback_url}?{error_params}", status_code=HTTP_303_SEE_OTHER
                )
        raise NotAuthorizedException(f"OAuth authorization failed: {error or 'No code received'}")

    # Validate oauth_state exists
    if not oauth_state or not await _saas_oauth_states.contains(oauth_state):
        raise NotAuthorizedException("Invalid OAuth state - possible CSRF attack")

    # Get and remove state data (one-time use)
    state_data = await _saas_oauth_states.pop(oauth_state)
    if not state_data:
        raise NotAuthorizedException("OAuth state not found")

    # Check expiry
    if state_data["expires_at"] < datetime.now(UTC):
        raise NotAuthorizedException("OAuth state expired. Please try again.")

    # Get callback info
    callback_url = state_data["callback_url"]
    stored_client_id = state_data["client_id"]

    # Get OAuth credentials
    stmt = select(AppSettings).where(AppSettings.id == 1)
    result = await session.execute(stmt)
    app_settings = result.scalar_one_or_none()

    if (
        not app_settings
        or not app_settings.polar_client_id
        or not app_settings.polar_client_secret_encrypted
    ):
        error_params = urlencode({"error": "server_not_configured", "status": "failed"})
        return Redirect(path=f"{callback_url}?{error_params}", status_code=HTTP_303_SEE_OTHER)

    # Exchange code for access token
    client_secret = token_encryption.decrypt(app_settings.polar_client_secret_encrypted)
    # Extract host/scheme from request headers (Coolify/nginx sets x-forwarded-*)
    scheme = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost:8000")
    base_url = f"{scheme}://{host}"
    redirect_uri = f"{base_url}/oauth/callback"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://polarremote.com/v2/oauth2/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                auth=(app_settings.polar_client_id, client_secret),
            )
            response.raise_for_status()
            token_data = response.json()

        # Get user ID from token response
        x_user_id = token_data.get("x_user_id")
        if x_user_id is None:
            error_params = urlencode({"error": "missing_user_id", "status": "failed"})
            return Redirect(path=f"{callback_url}?{error_params}", status_code=HTTP_303_SEE_OTHER)

        polar_user_id = str(x_user_id)
        access_token_encrypted = token_encryption.encrypt(token_data["access_token"])

        # Calculate token expiry
        expires_in = token_data.get("expires_in", 31536000)
        token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

        # Create or update user
        user_stmt = select(User).where(User.polar_user_id == polar_user_id)
        user_result = await session.execute(user_stmt)
        existing_user = user_result.scalar_one_or_none()

        if existing_user:
            existing_user.access_token_encrypted = access_token_encrypted
            existing_user.token_expires_at = token_expires_at
            existing_user.is_active = True
        else:
            new_user = User(
                polar_user_id=polar_user_id,
                access_token_encrypted=access_token_encrypted,
                token_expires_at=token_expires_at,
                is_active=True,
            )
            session.add(new_user)

        await session.flush()

        # Generate temporary auth code
        _, raw_temp_code = await create_temp_auth_code(
            user_id=polar_user_id,
            session=session,
            client_id=stored_client_id,
        )

        await session.commit()

        logger.info(f"SaaS OAuth completed for user {polar_user_id}")

        # Redirect to client callback with temp code (NOT the API key!)
        success_params = urlencode(
            {
                "code": raw_temp_code,
                "polar_user_id": polar_user_id,
                "status": "connected",
            }
        )
        return Redirect(path=f"{callback_url}?{success_params}", status_code=HTTP_303_SEE_OTHER)

    except Exception as e:
        logger.exception(f"SaaS OAuth callback failed: {e}")
        await session.rollback()
        error_params = urlencode({"error": str(e), "status": "failed"})
        return Redirect(path=f"{callback_url}?{error_params}", status_code=HTTP_303_SEE_OTHER)


# ==============================================================================
# OAuth Code Exchange Endpoint
# ==============================================================================


@post("/oauth/exchange", status_code=HTTP_201_CREATED)
async def exchange_oauth_code(
    data: OAuthExchangeRequest,
    session: AsyncSession,
) -> OAuthExchangeResponse:
    """Exchange a temporary OAuth code for an API key.

    This is the second step of the secure OAuth flow:
    1. User completes OAuth, gets temp code in redirect URL
    2. Client exchanges temp code server-to-server for API key

    The temp code is single-use and expires after 5 minutes.
    """
    # Exchange the temp code
    temp_code = await exchange_temp_code(
        raw_code=data.code,
        session=session,
        expected_client_id=data.client_id,
    )

    if temp_code is None:
        logger.warning("Invalid or expired temp code exchange attempted")
        raise NotAuthorizedException("Invalid or expired authorization code")

    user_id = temp_code.user_id

    # Check if user already has an API key - regenerate if so
    result = await session.execute(
        select(APIKey).where(APIKey.user_id == user_id, APIKey.is_active == True)  # noqa: E712
    )
    existing_key = result.scalar_one_or_none()

    if existing_key:
        # Regenerate existing key
        raw_key = await regenerate_api_key(existing_key, session)
        logger.info(f"Regenerated API key for user {user_id} via OAuth exchange")
    else:
        # Create new key
        _, raw_key = await create_api_key_for_user(
            user_id=user_id,
            name=f"OAuth key for {user_id}",
            session=session,
        )
        logger.info(f"Created new API key for user {user_id} via OAuth exchange")

    await session.commit()

    return OAuthExchangeResponse(
        api_key=raw_key,
        polar_user_id=user_id,
        expires_at=None,
    )


# ==============================================================================
# Key Management Endpoints (require authentication)
# ==============================================================================


@post("/users/{user_id:str}/api-key/regenerate", status_code=HTTP_200_OK)
async def regenerate_user_key(
    user_id: str,
    session: AsyncSession,
) -> KeyRegenerateResponse:
    """Regenerate the API key for a user.

    Invalidates the old key and returns a new one.
    Requires a valid API key for this user (or service-level key).
    """
    # Find user's active API key
    result = await session.execute(
        select(APIKey).where(APIKey.user_id == user_id, APIKey.is_active == True)  # noqa: E712
    )
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise NotFoundException(f"No active API key found for user {user_id}")

    # Regenerate
    raw_key = await regenerate_api_key(api_key, session)
    await session.commit()

    logger.info(f"API key regenerated for user {user_id}")

    return KeyRegenerateResponse(api_key=raw_key)


@post("/users/{user_id:str}/api-key/revoke", status_code=HTTP_200_OK)
async def revoke_user_key(
    user_id: str,
    session: AsyncSession,
) -> dict[str, Any]:
    """Revoke the API key for a user.

    Permanently deactivates the key without generating a new one.
    User will need to reconnect via OAuth to get a new key.
    """
    # Find user's active API key
    result = await session.execute(
        select(APIKey).where(APIKey.user_id == user_id, APIKey.is_active == True)  # noqa: E712
    )
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise NotFoundException(f"No active API key found for user {user_id}")

    # Revoke
    await revoke_api_key(api_key, session)
    await session.commit()

    logger.info(f"API key revoked for user {user_id}")

    return {"message": "API key revoked successfully", "user_id": user_id}


@get("/users/{user_id:str}/api-key/info", status_code=HTTP_200_OK)
async def get_key_info(
    user_id: str,
    session: AsyncSession,
) -> KeyInfoResponse | None:
    """Get information about a user's API key (masked).

    Returns key metadata without revealing the actual key.
    """
    result = await session.execute(
        select(APIKey).where(APIKey.user_id == user_id, APIKey.is_active == True)  # noqa: E712
    )
    api_key = result.scalar_one_or_none()

    if api_key is None:
        return None

    return KeyInfoResponse(
        key_prefix=api_key.key_prefix,
        user_id=api_key.user_id,
        is_active=api_key.is_active,
        rate_limit_requests=api_key.rate_limit_requests,
        rate_limit_remaining=api_key.rate_limit_remaining,
        created_at=str(api_key.created_at),
        last_used_at=str(api_key.last_used_at) if api_key.last_used_at else None,
    )


@get("/users/{user_id:str}/status", status_code=HTTP_200_OK)
async def get_user_status(
    user_id: str,
    session: AsyncSession,
) -> UserStatusResponse:
    """Get connection status for a user.

    Returns user info and API key status.
    """
    # Get user
    result = await session.execute(select(User).where(User.polar_user_id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise NotFoundException(f"User {user_id} not found")

    # Get API key info
    key_result = await session.execute(
        select(APIKey).where(APIKey.user_id == user_id, APIKey.is_active == True)  # noqa: E712
    )
    api_key = key_result.scalar_one_or_none()

    return UserStatusResponse(
        polar_user_id=user.polar_user_id,
        is_active=user.is_active,
        last_synced_at=str(user.last_synced_at) if user.last_synced_at else None,
        has_api_key=api_key is not None,
        api_key_prefix=api_key.key_prefix if api_key else None,
    )


# ==============================================================================
# Router
# ==============================================================================

# OAuth endpoints (no auth required - start and callback, plus code exchange)
oauth_router = Router(
    path="/",
    route_handlers=[
        oauth_start_saas,
        oauth_callback_saas,
        exchange_oauth_code,
    ],
)

# Key management endpoints (require per-user auth)
keys_router = Router(
    path="/",
    guards=[per_user_api_key_guard],
    route_handlers=[
        regenerate_user_key,
        revoke_user_key,
        get_key_info,
        get_user_status,
    ],
)
