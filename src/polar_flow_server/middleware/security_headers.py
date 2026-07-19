"""Security response headers (issue #54).

Static hardening headers on every response. The CSP is honest about what the
admin UI needs today (inline scripts + the HTMX/Tailwind/Chart.js CDNs) —
it won't stop inline-script injection, but it does block loading attacker
scripts from anywhere else, framing, form exfiltration, and plugin content.
Tightening to nonces is a follow-up once the inline scripts move to files.
"""

from litestar.datastructures import MutableScopeHeaders
from litestar.enums import ScopeType
from litestar.types import ASGIApp, Message, Receive, Scope, Send

_CSP = "; ".join(
    [
        "default-src 'self'",
        # Inline scripts are used heavily by the admin templates; CDNs pinned
        # to the three hosts base.html actually loads from
        "script-src 'self' 'unsafe-inline' "
        "https://unpkg.com https://cdn.tailwindcss.com https://cdn.jsdelivr.net",
        # Tailwind's CDN build injects styles at runtime; swagger css from jsdelivr
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "img-src 'self' data:",
        "font-src 'self' data: https://cdn.jsdelivr.net",
        "connect-src 'self'",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
)

SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": _CSP,
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

# Only meaningful over TLS; browsers ignore it on plain http, but don't
# advertise it unless the request actually arrived via https at the edge.
_HSTS_VALUE = "max-age=15768000"  # 6 months


class SecurityHeadersMiddleware:
    """ASGI middleware adding security headers to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != ScopeType.HTTP:
            await self.app(scope, receive, send)
            return

        # TLS terminates at the reverse proxy; it tells us via X-Forwarded-Proto
        request_headers = dict(scope.get("headers") or [])
        forwarded_proto = request_headers.get(b"x-forwarded-proto", b"").decode("latin-1")
        is_https = scope.get("scheme") == "https" or forwarded_proto == "https"

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableScopeHeaders.from_message(message)
                for name, value in SECURITY_HEADERS.items():
                    if name not in headers:
                        headers[name] = value
                if is_https and "Strict-Transport-Security" not in headers:
                    headers["Strict-Transport-Security"] = _HSTS_VALUE
            await send(message)

        await self.app(scope, receive, send_wrapper)
