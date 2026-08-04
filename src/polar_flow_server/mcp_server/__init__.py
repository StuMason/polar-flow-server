"""MCP server exposing the health data to AI assistants (issue #80).

Speaks MCP protocol revision 2026-07-28 over streamable HTTP, mounted at
``/mcp`` inside the main Litestar app and guarded by the same API keys as
the REST API.
"""

from polar_flow_server.mcp_server.asgi import create_mcp_mount
from polar_flow_server.mcp_server.server import build_mcp_server

__all__ = ["build_mcp_server", "create_mcp_mount"]
