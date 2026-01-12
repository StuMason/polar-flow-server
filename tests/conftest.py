"""Shared test fixtures."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from polar_flow_server.models.base import Base


@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def async_engine():
    """Create async SQLite engine for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Enable foreign keys for SQLite
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def async_session(async_engine) -> AsyncIterator[AsyncSession]:
    """Create async session for testing."""
    async_session_maker = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_maker() as session:
        yield session


@pytest.fixture
async def test_user(async_session: AsyncSession):
    """Create a test user."""
    from polar_flow_server.models.user import User

    user = User(
        id="test-user-uuid-1",
        polar_user_id="polar_user_001",
        access_token_encrypted="encrypted_token_placeholder",
        token_expires_at=datetime.now(UTC) + timedelta(days=365),
        is_active=True,
    )
    async_session.add(user)
    await async_session.commit()
    await async_session.refresh(user)
    return user


@pytest.fixture
async def test_user_2(async_session: AsyncSession):
    """Create a second test user."""
    from polar_flow_server.models.user import User

    user = User(
        id="test-user-uuid-2",
        polar_user_id="polar_user_002",
        access_token_encrypted="encrypted_token_placeholder",
        token_expires_at=datetime.now(UTC) + timedelta(days=365),
        is_active=True,
    )
    async_session.add(user)
    await async_session.commit()
    await async_session.refresh(user)
    return user


@pytest.fixture
async def user_api_key(async_session: AsyncSession, test_user):
    """Create a user-scoped API key."""
    from polar_flow_server.core.api_keys import create_api_key_for_user

    api_key, raw_key = await create_api_key_for_user(
        user_id=test_user.polar_user_id,
        name="Test User Key",
        session=async_session,
    )
    await async_session.commit()
    return api_key, raw_key


@pytest.fixture
async def service_api_key(async_session: AsyncSession):
    """Create a service-level API key."""
    from polar_flow_server.core.api_keys import create_service_key

    api_key, raw_key = await create_service_key(
        name="Test Service Key",
        session=async_session,
    )
    await async_session.commit()
    return api_key, raw_key


@pytest.fixture
async def temp_auth_code(async_session: AsyncSession, test_user):
    """Create a temporary auth code."""
    from polar_flow_server.core.api_keys import create_temp_auth_code

    temp_code, raw_code = await create_temp_auth_code(
        user_id=test_user.polar_user_id,
        session=async_session,
        client_id="test_client",
    )
    await async_session.commit()
    return temp_code, raw_code
