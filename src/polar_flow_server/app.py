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
from polar_flow_server.core.database import (
    async_session_maker,
    close_database,
    engine,
    init_database,
)
from polar_flow_server.middleware import RateLimitHeadersMiddleware
from polar_flow_server.routes import root_redirect
from polar_flow_server.services.scheduler import SyncScheduler, set_scheduler

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
    - Start background sync scheduler
    - Close database connections on shutdown
    - Stop scheduler on shutdown
    """
    logger.info(
        "Starting polar-flow-server",
        version=__version__,
        mode=settings.deployment_mode.value,
        sync_enabled=settings.sync_enabled,
        sync_interval=settings.sync_interval_minutes,
    )

    # Initialize database tables
    await init_database()
    logger.info("Database initialized")

    # Start background sync scheduler
    scheduler = SyncScheduler(async_session_maker)
    set_scheduler(scheduler)
    await scheduler.start()

    yield

    # Stop scheduler
    await scheduler.stop()

    # Cleanup database
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

    # Session middleware config with explicit security settings
    # Note: We don't set secure=True because Coolify/nginx terminates SSL
    # and forwards HTTP internally. The cookies would be rejected over HTTP.
    # Security is still enforced at the proxy level.
    session_config = ServerSideSessionConfig(
        key=settings.get_session_secret(),
        store="session_store",
        max_age=86400,  # 24 hours
        httponly=True,  # Prevent JS access to session cookie
        samesite="lax",  # CSRF protection
    )

    # CSRF protection config
    # Note: HTMX and our JS already send CSRF token in X-CSRF-Token header,
    # so most admin routes can (and should) require CSRF validation.
    csrf_config = CSRFConfig(
        secret=settings.get_session_secret(),
        cookie_name="csrf_token",
        header_name="X-CSRF-Token",
        cookie_httponly=False,  # JS needs to read this cookie to send in header
        exclude=[
            # Entry points (no session yet)
            "/admin/login",
            "/admin/setup",
            # External OAuth callbacks (redirects from Polar)
            "/admin/oauth/callback",
            "/oauth/",  # SaaS OAuth flow (callback, exchange, start)
            # Safe to exclude (just destroys session)
            "/admin/logout",
            # API routes use API key auth, not CSRF
            "/api/v1/users/",
            # Health check (no auth needed)
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
