"""Database initialization and session management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from polar_flow_server.core.config import settings
from polar_flow_server.models.base import Base


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
        pool_pre_ping=True,  # Verify connections before using
    )


# Global engine and session maker
engine = create_engine()
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_database() -> None:
    """Initialize database tables.

    Creates all tables defined in models if they don't exist.
    Safe to run multiple times (idempotent).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


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
