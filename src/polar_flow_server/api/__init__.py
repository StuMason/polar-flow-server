"""API routes."""

from polar_flow_server.api.health import health_router
from polar_flow_server.api.sleep import sleep_router
from polar_flow_server.api.sync import sync_router

# All API routers
api_routers = [
    health_router,
    sleep_router,
    sync_router,
]

__all__ = ["api_routers"]
