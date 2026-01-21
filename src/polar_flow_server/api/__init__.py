"""API routes."""

from litestar import Router

from polar_flow_server.api.baselines import baselines_router
from polar_flow_server.api.data import data_router
from polar_flow_server.api.export import export_router
from polar_flow_server.api.health import health_router
from polar_flow_server.api.insights import insights_router
from polar_flow_server.api.keys import keys_router, oauth_router
from polar_flow_server.api.patterns import patterns_router
from polar_flow_server.api.sleep import sleep_router
from polar_flow_server.api.sync import sync_router

# Versioned API routers (user data endpoints)
# These get the /api/v1 prefix
_v1_routers = [
    sleep_router,
    sync_router,
    data_router,
    baselines_router,  # Analytics baselines
    patterns_router,  # Pattern detection and anomalies
    insights_router,  # Unified insights API
    keys_router,  # Key management (regenerate, revoke, status)
    export_router,  # CSV data export
]

api_v1_router = Router(path="/api/v1", route_handlers=_v1_routers)

# Export: health (root), oauth (root), v1 (prefixed)
# - health_router: /health - no auth needed, no version prefix
# - oauth_router: /oauth/* - external OAuth flow, no version prefix
# - api_v1_router: /api/v1/* - all user data endpoints
api_routers = [health_router, oauth_router, api_v1_router]

__all__ = ["api_routers"]
