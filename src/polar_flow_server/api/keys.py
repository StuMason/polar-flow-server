"""API key management endpoints.

Provides endpoints for:
- OAuth code exchange (get API key from temp code)
- Key regeneration
- Key revocation
- User status
- SaaS OAuth start (for external clients like Laravel)
"""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from litestar import Request, Router, get, post
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
from polar_flow_server.models.api_key import APIKey
from polar_flow_server.models.settings import AppSettings
from polar_flow_server.models.user import User

# Store OAuth states with their callback URLs
# Format: {state: {"expires_at": datetime, "callback_url": str, "client_id": str | None}}
_saas_oauth_states: dict[str, dict[str, Any]] = {}

logger = logging.getLogger(__name__)


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
    request: Request,
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
    # Get OAuth credentials from database
    stmt = select(AppSettings).where(AppSettings.id == 1)
    result = await session.execute(stmt)
    app_settings = result.scalar_one_or_none()

    if not app_settings or not app_settings.polar_client_id:
        raise NotFoundException("OAuth credentials not configured on server")

    # Generate CSRF state token
    state = secrets.token_urlsafe(32)
    _saas_oauth_states[state] = {
        "expires_at": datetime.now(UTC) + timedelta(minutes=10),
        "callback_url": callback_url,
        "client_id": client_id,
    }

    # Clean up expired states
    now = datetime.now(UTC)
    expired = [s for s, data in _saas_oauth_states.items() if data["expires_at"] < now]
    for s in expired:
        del _saas_oauth_states[s]

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
    request: Request,
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

    # Handle errors
    if error or not code:
        # Redirect to callback with error if we have oauth_state
        if oauth_state and oauth_state in _saas_oauth_states:
            callback_url = _saas_oauth_states[oauth_state]["callback_url"]
            del _saas_oauth_states[oauth_state]
            error_params = urlencode({"error": error or "no_code", "status": "failed"})
            return Redirect(path=f"{callback_url}?{error_params}", status_code=HTTP_303_SEE_OTHER)
        raise NotAuthorizedException(f"OAuth authorization failed: {error or 'No code received'}")

    # Validate oauth_state
    if not oauth_state or oauth_state not in _saas_oauth_states:
        raise NotAuthorizedException("Invalid OAuth state - possible CSRF attack")

    state_data = _saas_oauth_states[oauth_state]

    # Check expiry
    if state_data["expires_at"] < datetime.now(UTC):
        del _saas_oauth_states[oauth_state]
        raise NotAuthorizedException("OAuth state expired. Please try again.")

    # Get callback info and remove oauth_state (one-time use)
    callback_url = state_data["callback_url"]
    stored_client_id = state_data["client_id"]
    del _saas_oauth_states[oauth_state]

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
