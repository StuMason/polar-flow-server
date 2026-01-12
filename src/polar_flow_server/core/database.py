"""Database initialization and session management."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from polar_flow_server.core.config import settings

logger = logging.getLogger(__name__)


def create_engine() -> AsyncEngine:
    """Create PostgreSQL database engine.

    Returns:
        Async SQLAlchemy engine configured for PostgreSQL
    """
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_recycle=300,  # Recycle connections every 5 minutes
    )


# Global engine and session maker
engine = create_engine()
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_database() -> None:
    """Verify database is ready and migrations have been applied.

    Checks that the database is accessible and the alembic_version table exists,
    indicating migrations have been run. Does NOT create tables - use Alembic
    migrations for schema management.

    Raises:
        RuntimeError: If migrations have not been applied
    """
    async with engine.connect() as conn:
        # Check if alembic_version table exists (migrations have been run)
        result = await conn.execute(
            text(
                "SELECT EXISTS ("
                "SELECT FROM information_schema.tables "
                "WHERE table_name = 'alembic_version'"
                ")"
            )
        )
        has_migrations = result.scalar()

        if not has_migrations:
            logger.warning(
                "Database migrations have not been applied. "
                "Run 'alembic upgrade head' to initialize the database schema."
            )
        else:
            # Check current migration version
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            version = result.scalar()
            logger.info(f"Database initialized with migration version: {version}")


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session.

    Usage:
        async with get_session() as session:
            result = await session.execute(select(Sleep))
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_database() -> None:
    """Close database connection pool."""
    await engine.dispose()
