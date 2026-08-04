"""OAuth 2.1 authorization server + token verification for the MCP endpoint.

The SDK provides the protocol endpoints (/authorize, /token, /register,
/revoke, discovery metadata) and PKCE verification; this module supplies the
storage-backed provider behind them and the token verifier the resource
server uses. The human half of /authorize - admin login and the consent
screen - lives in the admin routes; the handoff between the two is a signed,
expiring blob of the authorization params (no server-side pending-auth
state).

Token verification is the single auth funnel for /mcp in OAuth mode: it
accepts issued OAuth access tokens AND raw API keys presented as bearers,
resolving both to the same KeyScope contextvar the tools read.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Any

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
    TokenVerifier,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import update

from polar_flow_server.core.auth import KeyScope, hash_api_key, resolve_key_scope
from polar_flow_server.core.config import settings
from polar_flow_server.mcp_server.context import current_key_scope
from polar_flow_server.models.oauth import OAuthAuthCode, OAuthClient, OAuthIssuedToken

ACCESS_TOKEN_TTL_SECONDS = 3600
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 3600
AUTH_CODE_TTL_SECONDS = 300
CONSENT_BLOB_TTL_SECONDS = 600

OAUTH_SCOPE = "health"


def _sign(payload: bytes) -> str:
    key = settings.get_session_secret().encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def pack_consent_request(client_id: str, params: AuthorizationParams) -> str:
    """Serialize + sign the authorization params for the consent redirect."""
    payload = json.dumps(
        {
            "client_id": client_id,
            "state": params.state,
            "scopes": params.scopes,
            "code_challenge": params.code_challenge,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "resource": params.resource,
            "exp": time.time() + CONSENT_BLOB_TTL_SECONDS,
        }
    ).encode()
    blob = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"{blob}.{_sign(payload)}"


def unpack_consent_request(blob: str) -> dict[str, Any] | None:
    """Verify and decode a consent blob; None if tampered or expired."""
    try:
        body, signature = blob.rsplit(".", 1)
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(_sign(payload), signature):
        return None
    data: dict[str, Any] = json.loads(payload)
    if time.time() > data["exp"]:
        return None
    return data


class PolarOAuthProvider:
    """Storage-backed OAuthAuthorizationServerProvider.

    Sessions are opened per call via async_session_maker - the SDK invokes
    these outside Litestar's dependency injection.
    """

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        from polar_flow_server.core.database import async_session_maker

        async with async_session_maker() as session:
            row = await session.get(OAuthClient, client_id)
        if row is None:
            return None
        return OAuthClientInformationFull.model_validate(row.client_metadata)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        from polar_flow_server.core.database import async_session_maker

        async with async_session_maker() as session:
            session.add(
                OAuthClient(
                    client_id=client_info.client_id,
                    client_metadata=client_info.model_dump(mode="json"),
                )
            )
            await session.commit()

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        # Hand off to the human: admin login + consent page render the
        # decision; the signed blob carries everything needed to mint the
        # code once approved.
        return f"{settings.base_url}/admin/oauth/consent?req={pack_consent_request(client.client_id, params)}"

    async def create_authorization_code(self, data: dict[str, Any], subject: str) -> str:
        """Mint and store a code for an approved consent (called by the
        consent route, not the SDK)."""
        from polar_flow_server.core.database import async_session_maker

        code = f"pfc_{secrets.token_urlsafe(32)}"
        async with async_session_maker() as session:
            session.add(
                OAuthAuthCode(
                    code_hash=hash_api_key(code),
                    client_id=data["client_id"],
                    subject=subject,
                    scopes=data["scopes"] or [OAUTH_SCOPE],
                    expires_at=time.time() + AUTH_CODE_TTL_SECONDS,
                    code_challenge=data["code_challenge"],
                    redirect_uri=data["redirect_uri"],
                    redirect_uri_provided_explicitly=data["redirect_uri_provided_explicitly"],
                    resource=data.get("resource"),
                )
            )
            await session.commit()
        return code

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        from polar_flow_server.core.database import async_session_maker

        async with async_session_maker() as session:
            row = await session.get(OAuthAuthCode, hash_api_key(authorization_code))
        if row is None or row.client_id != client.client_id or time.time() > row.expires_at:
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=list(row.scopes),
            expires_at=row.expires_at,
            client_id=row.client_id,
            code_challenge=row.code_challenge,
            redirect_uri=row.redirect_uri,
            redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
            resource=row.resource,
            subject=row.subject,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        from polar_flow_server.core.database import async_session_maker

        subject = authorization_code.subject or ""
        async with async_session_maker() as session:
            # Single use: delete before issuing; a replayed code gets nothing
            row = await session.get(OAuthAuthCode, hash_api_key(authorization_code.code))
            if row is None:
                raise TokenError("invalid_grant", "Authorization code already used")
            await session.delete(row)
            token = await self._issue_pair(
                session, client.client_id, subject, authorization_code.scopes
            )
            await session.commit()
        return token

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        from polar_flow_server.core.database import async_session_maker

        async with async_session_maker() as session:
            row = await session.get(OAuthIssuedToken, hash_api_key(refresh_token))
        if (
            row is None
            or row.token_type != "refresh"
            or row.revoked
            or row.client_id != client.client_id
            or (row.expires_at is not None and time.time() > row.expires_at)
        ):
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=row.client_id,
            scopes=list(row.scopes),
            expires_at=int(row.expires_at) if row.expires_at else None,
            subject=row.subject,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        from polar_flow_server.core.database import async_session_maker

        async with async_session_maker() as session:
            row = await session.get(OAuthIssuedToken, hash_api_key(refresh_token.token))
            if row is None or row.revoked:
                raise TokenError("invalid_grant", "Refresh token is no longer valid")
            # Rotate: retire the whole old pair, issue a fresh one
            await session.execute(
                update(OAuthIssuedToken)
                .where(OAuthIssuedToken.pair_id == row.pair_id)
                .values(revoked=True)
            )
            token = await self._issue_pair(
                session, client.client_id, row.subject, scopes or list(row.scopes)
            )
            await session.commit()
        return token

    async def load_access_token(self, token: str) -> AccessToken | None:
        from polar_flow_server.core.database import async_session_maker

        async with async_session_maker() as session:
            row = await session.get(OAuthIssuedToken, hash_api_key(token))
        if (
            row is None
            or row.token_type != "access"
            or row.revoked
            or (row.expires_at is not None and time.time() > row.expires_at)
        ):
            return None
        return AccessToken(
            token=token,
            client_id=row.client_id,
            scopes=list(row.scopes),
            expires_at=int(row.expires_at) if row.expires_at else None,
            subject=row.subject,
        )

    async def exchange_identity_assertion(
        self, client: OAuthClientInformationFull, params: Any
    ) -> OAuthToken:
        """Identity-assertion grants are not supported (feature disabled)."""
        raise NotImplementedError("Identity assertion is not supported")

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        from polar_flow_server.core.database import async_session_maker

        async with async_session_maker() as session:
            row = await session.get(OAuthIssuedToken, hash_api_key(token.token))
            if row is None:
                return
            # Revoke the pair, per OAuth 2.1 SHOULD
            await session.execute(
                update(OAuthIssuedToken)
                .where(OAuthIssuedToken.pair_id == row.pair_id)
                .values(revoked=True)
            )
            await session.commit()

    async def _issue_pair(
        self, session: Any, client_id: str, subject: str, scopes: list[str]
    ) -> OAuthToken:
        access = f"pfa_{secrets.token_urlsafe(32)}"
        refresh = f"pfr_{secrets.token_urlsafe(32)}"
        pair_id = str(uuid.uuid4())
        now = time.time()
        session.add(
            OAuthIssuedToken(
                token_hash=hash_api_key(access),
                token_type="access",
                pair_id=pair_id,
                client_id=client_id,
                subject=subject,
                scopes=scopes,
                expires_at=now + ACCESS_TOKEN_TTL_SECONDS,
            )
        )
        session.add(
            OAuthIssuedToken(
                token_hash=hash_api_key(refresh),
                token_type="refresh",
                pair_id=pair_id,
                client_id=client_id,
                subject=subject,
                scopes=scopes,
                expires_at=now + REFRESH_TOKEN_TTL_SECONDS,
            )
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(scopes) if scopes else None,
            refresh_token=refresh,
        )


class PolarTokenVerifier(TokenVerifier):
    """Single auth funnel for /mcp bearers: OAuth tokens and raw API keys.

    Sets the KeyScope contextvar the tools read. If the mount already
    resolved an X-API-Key header (and injected it as a bearer), the existing
    contextvar short-circuits re-validation so rate-limit slots aren't
    double-consumed.
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        existing = current_key_scope.get()
        if existing is not None:
            return _scope_to_access_token(token, existing)

        # Issued OAuth access token?
        provider = PolarOAuthProvider()
        access = await provider.load_access_token(token)
        if access is not None:
            current_key_scope.set(
                KeyScope(user_id=access.subject, api_key_id=None, rate_limit_info=None)
            )
            return access

        # Raw API key presented as a bearer (headless clients)
        try:
            scope = await resolve_key_scope(token)
        except Exception:  # invalid key or rate-limited -> not authenticated
            return None
        current_key_scope.set(scope)
        return _scope_to_access_token(token, scope)


def _scope_to_access_token(token: str, scope: KeyScope) -> AccessToken:
    return AccessToken(
        token=token,
        client_id=f"api-key-{scope.api_key_id}" if scope.api_key_id else "api-key-master",
        scopes=[OAUTH_SCOPE],
        expires_at=None,
        subject=scope.user_id,
    )


def build_consent_redirect(data: dict[str, Any], code: str) -> str:
    """Redirect URI back to the client with the freshly-minted code."""
    return construct_redirect_uri(data["redirect_uri"], code=code, state=data["state"])
