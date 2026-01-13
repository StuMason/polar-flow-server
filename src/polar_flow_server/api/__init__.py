"""API routes."""

from polar_flow_server.api.baselines import baselines_router
from polar_flow_server.api.data import data_router
from polar_flow_server.api.health import health_router
from polar_flow_server.api.insights import insights_router
from polar_flow_server.api.keys import keys_router, oauth_router
from polar_flow_server.api.patterns import patterns_router
from polar_flow_server.api.sleep import sleep_router
from polar_flow_server.api.sync import sync_router

# All API routers
api_routers = [
    health_router,
    sleep_router,
    sync_router,
    data_router,
    baselines_router,  # Analytics baselines
    patterns_router,  # Pattern detection and anomalies
    insights_router,  # Unified insights API
    oauth_router,  # OAuth flow and code exchange
    keys_router,  # Key management (regenerate, revoke, status)
]

__all__ = ["api_routers"]
