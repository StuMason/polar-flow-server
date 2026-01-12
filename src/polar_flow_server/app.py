"""Litestar application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from advanced_alchemy.config.asyncio import AsyncSessionConfig
from litestar import Litestar
from litestar.config.csrf import CSRFConfig
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.contrib.sqlalchemy.plugins import SQLAlchemyAsyncConfig, SQLAlchemyPlugin
from litestar.middleware.session.server_side import ServerSideSessionConfig
from litestar.openapi import OpenAPIConfig
from litestar.stores.memory import MemoryStore
from litestar.template.config import TemplateConfig

from polar_flow_server import __version__
from polar_flow_server.admin import admin_router
from polar_flow_server.api import api_routers
from polar_flow_server.core.config import settings
from polar_flow_server.core.database import close_database, engine, init_database
from polar_flow_server.middleware import RateLimitHeadersMiddleware
from polar_flow_server.routes import root_redirect

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncIterator[None]:
    """Application lifespan manager.

    Handles startup and shutdown tasks:
    - Initialize database on startup
    - Close database connections on shutdown
    """
    logger.info(
        "Starting polar-flow-server",
        version=__version__,
        mode=settings.deployment_mode.value,
    )

    # Initialize database tables
    await init_database()
    logger.info("Database initialized")

    yield

    # Cleanup
    await close_database()
    logger.info("Shutdown complete")


def create_app() -> Litestar:
    """Create Litestar application.

    Returns:
        Configured Litestar app instance
    """
    # Get templates directory path
    templates_dir = Path(__file__).parent / "templates"

    # Session store for admin authentication
    # In production with multiple instances, use Redis instead
    session_store = MemoryStore()

    # Session middleware config
    session_config = ServerSideSessionConfig(
        key=settings.get_session_secret(),
        store="session_store",
        max_age=86400,  # 24 hours
    )

    # CSRF protection config
    csrf_config = CSRFConfig(
        secret=settings.get_session_secret(),
        cookie_name="csrf_token",
        header_name="X-CSRF-Token",
        exclude=[
            "/admin/login",  # Login form - entry point, no session yet
            "/admin/setup",  # Setup flow - entry point, no session yet
            "/admin/oauth/callback",  # OAuth callback from Polar (admin dashboard)
            "/admin/settings",  # Settings pages (reset-oauth, etc.)
            "/admin/sync",  # Sync trigger from dashboard
            "/admin/logout",  # Logout action
            "/oauth/",  # OAuth endpoints for SaaS (callback, exchange, start)
            "/users/",  # API routes use API key auth, not sessions
            "/health",
        ],
    )

    return Litestar(
        route_handlers=[root_redirect, *api_routers, admin_router],
        lifespan=[lifespan],
        openapi_config=OpenAPIConfig(
            title="polar-flow-server API",
            version=__version__,
            description="Self-hosted health analytics server for Polar devices",
        ),
        template_config=TemplateConfig(
            directory=templates_dir,
            engine=JinjaTemplateEngine,
        ),
        plugins=[
            SQLAlchemyPlugin(
                config=SQLAlchemyAsyncConfig(
                    engine_instance=engine,
                    session_dependency_key="session",
                    session_config=AsyncSessionConfig(expire_on_commit=False),
                ),
            ),
        ],
        middleware=[session_config.middleware, RateLimitHeadersMiddleware],
        csrf_config=csrf_config,
        stores={"session_store": session_store},
        debug=settings.log_level == "DEBUG",
    )


# Application instance
app = create_app()
