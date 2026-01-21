"""Admin panel for self-hosted deployments."""

from litestar import Router

from polar_flow_server.admin.routes import admin_routes

admin_router = Router(
    path="/admin", route_handlers=admin_routes, tags=["Admin"], include_in_schema=False
)

__all__ = ["admin_router"]
