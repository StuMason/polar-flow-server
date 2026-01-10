"""Litestar application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from litestar import Litestar
from litestar.contrib.sqlalchemy.plugins import SQLAlchemyAsyncConfig, SQLAlchemyPlugin
from litestar.openapi import OpenAPIConfig

from polar_flow_server import __version__
from polar_flow_server.api import api_routers
from polar_flow_server.core.config import settings
from polar_flow_server.core.database import close_database, engine, init_database

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
    return Litestar(
        route_handlers=api_routers,
        lifespan=[lifespan],
        openapi_config=OpenAPIConfig(
            title="polar-flow-server API",
            version=__version__,
            description="Self-hosted health analytics server for Polar devices",
        ),
        plugins=[
            SQLAlchemyPlugin(
                config=SQLAlchemyAsyncConfig(
                    engine_instance=engine,
                    session_dependency_key="session",
                ),
            ),
        ],
        debug=settings.log_level == "DEBUG",
    )


# Application instance
app = create_app()
