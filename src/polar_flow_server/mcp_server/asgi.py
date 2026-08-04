"""Litestar mount for the MCP endpoint, with API-key authentication.

The SDK's streamable-HTTP transport is a plain Starlette ASGI app; we mount
it at ``/mcp`` behind the same key validation the REST API uses
(``resolve_key_scope``). Auth happens at the HTTP layer BEFORE any MCP
protocol handling, so an unauthenticated request never reaches the protocol
code, and the resolved scope travels to tools via a contextvar.
"""

import json
from typing import Any, cast

from litestar import asgi
from litestar.exceptions import NotAuthorizedException
from litestar.handlers import ASGIRouteHandler
from litestar.types import Receive, Scope, Send
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from polar_flow_server.core.auth import RateLimitExceeded, resolve_key_scope
from polar_flow_server.mcp_server.context import current_key_scope

MCP_PATH = "/mcp"


def create_mcp_mount(server: MCPServer) -> ASGIRouteHandler:
    """Build the authenticated ``/mcp`` mount for a Litestar app."""
    mcp_asgi = server.streamable_http_app(
        streamable_http_path="/",
        # Host-header (DNS-rebinding) checks default to localhost-only and
        # would 421 behind the reverse proxy. Rebinding attacks are moot
        # here anyway: every request must carry an API key, which a rebound
        # browser origin cannot attach.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @asgi(MCP_PATH, is_mount=True, name="mcp", copy_scope=True)
    async def mcp_mount(scope: Scope, receive: Receive, send: Send) -> None:
        raw_key = _extract_api_key(scope)
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

        # Normalize the path for the sub-app: it serves at "/" and must see
        # the path with the mount prefix stripped, whatever Litestar passed.
        subpath = scope["path"]
        if subpath.startswith(MCP_PATH):
            subpath = subpath[len(MCP_PATH) :]
        sub_scope: Any = {**scope, "path": subpath or "/", "root_path": ""}

        token = current_key_scope.set(key_scope)
        try:
            # Litestar and Starlette type their ASGI callables differently;
            # both are the same protocol at runtime.
            await mcp_asgi(sub_scope, cast(Any, receive), cast(Any, send))
        finally:
            current_key_scope.reset(token)

    return mcp_mount


def _extract_api_key(scope: Scope) -> str | None:
    """Pull the API key from X-API-Key or Authorization: Bearer headers."""
    api_key: str | None = None
    bearer: str | None = None
    for name, value in scope.get("headers", []):
        lowered = name.lower()
        if lowered == b"x-api-key":
            api_key = value.decode("latin-1")
        elif lowered == b"authorization":
            decoded = value.decode("latin-1")
            if decoded.startswith("Bearer "):
                bearer = decoded[7:]
    return api_key or bearer


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
