"""Request-scoped authentication context for MCP tools.

The MCP endpoint authenticates each HTTP request before handing it to the
MCP protocol layer (see ``asgi.py``) and records the resolved key scope in a
contextvar. Tools never see raw headers — they resolve the effective user
through :func:`resolve_scoped_user_id`, which enforces the same authorization
model as the REST API's ``per_user_api_key_guard``.
"""

from contextvars import ContextVar

from sqlalchemy import select

from polar_flow_server.core.auth import KeyScope
from polar_flow_server.models.user import User

current_key_scope: ContextVar[KeyScope | None] = ContextVar("mcp_key_scope", default=None)


async def resolve_scoped_user_id(user_id: str | None) -> str:
    """Resolve the user a tool call is allowed to read.

    - User-scoped key: always that key's user; an explicit mismatching
      ``user_id`` argument is rejected.
    - Service-level or master key: the explicit ``user_id`` if given,
      otherwise the server's single connected user (the self-hosted case).

    Raises:
        ValueError: If unauthorized for the requested user, or no user exists.
    """
    scope = current_key_scope.get()
    if scope is None:
        raise ValueError("No authenticated API key scope for this MCP request")

    if scope.user_id is not None:
        if user_id is not None and user_id != scope.user_id:
            raise ValueError("API key not authorized for this user")
        return scope.user_id

    if user_id is not None:
        return user_id

    from polar_flow_server.core.database import async_session_maker

    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.is_active == True).limit(1))  # noqa: E712
        user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(
            "No connected Polar user on this server yet - complete the OAuth setup first"
        )
    return user.polar_user_id
