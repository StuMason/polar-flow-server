"""MCP server factory.

Built per Litestar app instance (never a module singleton): the SDK's
``session_manager.run()`` is single-use, and tests create the app repeatedly.

Speaks MCP protocol revision 2026-07-28 (and earlier revisions for older
clients) via the official ``mcp`` SDK v2.
"""

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.caching import CacheHint
from mcp.server.mcpserver import MCPServer

from polar_flow_server import __version__
from polar_flow_server.mcp_server import tools

INSTRUCTIONS = """\
Health analytics for one or more Polar device users: sleep, recovery (HRV /
nightly recharge / cardio load), activity, and exercise data synced from
Polar AccessLink, with per-user baselines, trends, patterns, and anomalies
computed server-side.

Start broad questions ("how am I doing?", "should I train hard today?") with
get_health_insights - it compares today's metrics to the user's own
baselines and includes ready-made observations. Reach for the per-domain
tools (get_sleep, get_recovery, ...) when you need day-by-day numbers to
analyze or chart. All dates are ISO YYYY-MM-DD; the server stores whatever
the watch recorded - missing dates mean the device wasn't worn.
"""

# Registration order == tools/list order (the SDK preserves insertion order).
# Keep stable; append new tools rather than reordering.
_TOOLS = (
    tools.get_health_insights,
    tools.get_sleep,
    tools.get_recovery,
    tools.get_activity,
    tools.get_exercises,
    tools.get_biosensing,
    tools.get_baselines,
    tools.get_patterns,
    tools.trigger_sync,
    tools.get_sync_status,
)


def build_mcp_server(
    token_verifier: TokenVerifier | None = None,
    auth: AuthSettings | None = None,
) -> MCPServer:
    """Create the MCP server with all tools registered.

    With ``token_verifier`` + ``auth`` (OAuth mode) the SDK guards the MCP
    route with bearer auth and serves protected-resource metadata; without
    them the mount in ``asgi.py`` does API-key auth itself.
    """
    server = MCPServer(
        name="polar-flow-server",
        title="Polar Health Data",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://github.com/StuMason/polar-flow-server",
        token_verifier=token_verifier,
        auth=auth,
        # The tool list only changes on deploy; let clients cache it. Health
        # data responses themselves are never cacheable by intermediaries.
        cache_hints={"tools/list": CacheHint(ttl_ms=3_600_000, scope="private")},
    )
    for fn in _TOOLS:
        server.tool()(fn)
    return server
