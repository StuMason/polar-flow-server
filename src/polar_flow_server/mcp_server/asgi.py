"""Litestar mounts for the MCP endpoint and the OAuth authorization server.

Two auth modes for ``/mcp``:

- **API-key only** (no ``BASE_URL`` configured): the mount validates
  X-API-Key / Bearer keys itself, exactly as the REST guard does, and
  rejects everything else before the protocol layer.
- **OAuth mode** (``BASE_URL`` set, self-hosted): the SDK's bearer
  middleware guards the MCP route through :class:`PolarTokenVerifier`, which
  accepts issued OAuth access tokens and raw API keys alike. Requests
  without credentials get the spec's 401 + ``WWW-Authenticate`` pointing at
  the protected-resource metadata - that discovery chain is what makes the
  "Connect" button in MCP clients work. X-API-Key headers are still
  honoured: the mount validates them (keeping the 429 rate-limit contract)
  and injects the key as a bearer so one pipeline authenticates.

The authorization-server endpoints (/authorize, /token, /register, /revoke,
/.well-known/*) must live at the site root - the issuer - not under /mcp,
so they're mounted as their own handlers.
"""

import json
from typing import Any, cast

from litestar import asgi
from litestar.exceptions import NotAuthorizedException
from litestar.handlers import ASGIRouteHandler
from litestar.types import Receive, Scope, Send
from mcp.server.auth.provider import OAuthAuthorizationServerProvider
from mcp.server.auth.routes import create_auth_routes, create_protected_resource_routes
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from polar_flow_server.core.auth import RateLimitExceeded, resolve_key_scope
from polar_flow_server.mcp_server.context import current_key_scope

MCP_PATH = "/mcp"

# Root-level paths the OAuth flow needs (see module docstring)
OAUTH_ROOT_PATHS = ("/.well-known", "/authorize", "/token", "/register", "/revoke")


def create_mcp_mount(server: MCPServer, *, oauth_enabled: bool = False) -> ASGIRouteHandler:
    """Build the ``/mcp`` mount for a Litestar app."""
    mcp_asgi = server.streamable_http_app(
        streamable_http_path="/",
        # Host-header (DNS-rebinding) checks default to localhost-only and
        # would 421 behind the reverse proxy. Rebinding attacks are moot
        # here anyway: every request must carry a credential a rebound
        # browser origin cannot attach.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @asgi(MCP_PATH, is_mount=True, name="mcp", copy_scope=True)
    async def mcp_mount(scope: Scope, receive: Receive, send: Send) -> None:
        # Normalize the path for the sub-app: it serves the MCP endpoint at
        # "/" and must see the mount prefix stripped, whatever Litestar passed.
        subpath = scope["path"]
        if subpath.startswith(MCP_PATH):
            subpath = subpath[len(MCP_PATH) :]
        sub_scope: Any = {**scope, "path": subpath or "/", "root_path": ""}

        async def delegate() -> None:
            await mcp_asgi(sub_scope, cast(Any, receive), cast(Any, send))

        if oauth_enabled:
            if sub_scope["path"] != "/":
                # Non-endpoint paths inside the sub-app (e.g. its copy of the
                # protected-resource metadata) are public.
                await delegate()
                return

            raw_x_key = _header(scope, b"x-api-key")
            if raw_x_key is None:
                # Bearer (OAuth token or API key) or no credentials at all:
                # the SDK middleware + PolarTokenVerifier decide, and produce
                # spec-compliant 401s with WWW-Authenticate.
                await delegate()
                return

            # Explicit X-API-Key keeps the legacy contract (429s intact)
            try:
                key_scope = await resolve_key_scope(raw_x_key)
            except RateLimitExceeded as exc:
                await _send_json(
                    send,
                    429,
                    {"error": str(exc.detail)},
                    extra_headers=[(b"retry-after", str(exc.retry_after).encode())],
                )
                return
            except NotAuthorizedException as exc:
                await _send_json(send, 401, {"error": str(exc.detail)})
                return

            if _header(scope, b"authorization") is None:
                # Feed the validated key through the bearer pipeline; the
                # verifier sees the contextvar and won't re-validate.
                sub_scope["headers"] = [
                    *sub_scope["headers"],
                    (b"authorization", b"Bearer " + raw_x_key.encode("latin-1")),
                ]
            token = current_key_scope.set(key_scope)
            try:
                await delegate()
            finally:
                current_key_scope.reset(token)
            return

        # API-key-only mode: authenticate here, before any protocol handling
        raw_key = _header(scope, b"x-api-key") or _bearer(scope)
        if not raw_key:
            await _send_json(send, 401, {"error": "Missing API key. Use X-API-Key header."})
            return

        try:
            key_scope = await resolve_key_scope(raw_key)
        except RateLimitExceeded as exc:
            await _send_json(
                send,
                429,
                {"error": str(exc.detail)},
                extra_headers=[(b"retry-after", str(exc.retry_after).encode())],
            )
            return
        except NotAuthorizedException as exc:
            await _send_json(send, 401, {"error": str(exc.detail)})
            return

        token = current_key_scope.set(key_scope)
        try:
            await delegate()
        finally:
            current_key_scope.reset(token)

    return mcp_mount


def create_oauth_root_mounts(
    provider: OAuthAuthorizationServerProvider[Any, Any, Any],
    auth: AuthSettings,
) -> list[ASGIRouteHandler]:
    """Mount the SDK's authorization-server routes at the site root."""
    oauth_app = Starlette(
        routes=[
            *create_auth_routes(
                provider=provider,
                issuer_url=auth.issuer_url,
                client_registration_options=auth.client_registration_options,
                revocation_options=auth.revocation_options,
            ),
            *create_protected_resource_routes(
                resource_url=auth.resource_server_url,  # type: ignore[arg-type]
                authorization_servers=[auth.issuer_url],
                scopes_supported=auth.required_scopes,
            ),
        ]
    )

    def make_handler(prefix: str) -> ASGIRouteHandler:
        @asgi(
            prefix,
            is_mount=True,
            name=f"oauth-{prefix.strip('/').replace('/', '-').replace('.', '')}",
            copy_scope=True,
        )
        async def handler(scope: Scope, receive: Receive, send: Send) -> None:
            # The Starlette app's routes use absolute root paths; restore the
            # prefix if the mount stripped it, and drop the trailing slash
            # Litestar appends (Starlette would slash-redirect forever).
            path = scope["path"]
            if not path.startswith(prefix):
                path = prefix + ("" if path == "/" else path)
            if len(path) > 1:
                path = path.rstrip("/")
            sub_scope: Any = {**scope, "path": path, "root_path": ""}
            await oauth_app(sub_scope, cast(Any, receive), cast(Any, send))

        return handler

    return [make_handler(prefix) for prefix in OAUTH_ROOT_PATHS]


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def _bearer(scope: Scope) -> str | None:
    auth_header = _header(scope, b"authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


async def _send_json(
    send: Send,
    status: int,
    body: dict[str, str],
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    """Send a minimal JSON response without entering the MCP app."""
    payload = json.dumps(body).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(payload)).encode()),
        *(extra_headers or []),
    ]
    await send(cast(Any, {"type": "http.response.start", "status": status, "headers": headers}))
    await send(cast(Any, {"type": "http.response.body", "body": payload}))
