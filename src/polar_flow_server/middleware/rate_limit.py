"""Rate limit response headers.

Adds X-RateLimit-* headers to responses for authenticated requests.
"""

from typing import Any

from litestar import Response
from litestar.connection import ASGIConnection
from litestar.types import ASGIApp, Message, Receive, Scope, Send

from polar_flow_server.core.auth import RATE_LIMIT_STATE_KEY


def add_rate_limit_headers(
    response: Response[Any], connection: ASGIConnection[Any, Any, Any, Any]
) -> Response[Any]:
    """Add rate limit headers to the response.

    This is an after_request hook that reads rate limit info from
    connection state (set by per_user_api_key_guard) and adds
    X-RateLimit-* headers to the response.

    Headers added:
    - X-RateLimit-Limit: Max requests per hour
    - X-RateLimit-Remaining: Remaining requests in current window
    - X-RateLimit-Reset: Unix timestamp when window resets
    """
    rate_limit_info = connection.state.get(RATE_LIMIT_STATE_KEY)

    if rate_limit_info:
        response.headers["X-RateLimit-Limit"] = str(rate_limit_info["limit"])
        response.headers["X-RateLimit-Remaining"] = str(rate_limit_info["remaining"])
        response.headers["X-RateLimit-Reset"] = str(rate_limit_info["reset"])

    return response


class RateLimitHeadersMiddleware:
    """Middleware to add rate limit headers to responses.

    Note: This middleware captures the state after the app processes the request,
    allowing it to access state set by guards during request processing.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Initialize middleware with the ASGI app."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process the request and add rate limit headers to response."""
        if scope["type"] != "http":  # type: ignore[comparison-overlap]
            await self.app(scope, receive, send)
            return

        # Initialize state dict if not present
        if "state" not in scope:
            scope["state"] = {}

        async def send_wrapper(message: Message) -> None:
            """Wrap send to inject rate limit headers."""
            if message["type"] == "http.response.start":
                rate_limit_info = scope.get("state", {}).get(RATE_LIMIT_STATE_KEY)
                if rate_limit_info:
                    headers = list(message.get("headers", []))
                    headers.extend(
                        [
                            (b"x-ratelimit-limit", str(rate_limit_info["limit"]).encode()),
                            (b"x-ratelimit-remaining", str(rate_limit_info["remaining"]).encode()),
                            (b"x-ratelimit-reset", str(rate_limit_info["reset"]).encode()),
                        ]
                    )
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
