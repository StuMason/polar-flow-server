"""Shared test fixtures."""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

# Integration tests (the `app_client` fixture) run the REAL app — lifespan,
# middleware, DI — against a dedicated Postgres database so they can never
# touch a developer's actual data. Must be set before any polar_flow_server
# import so the global Settings/engine pick it up. CI provides the matching
# postgres service container (see .github/workflows/tests.yml).
os.environ["DATABASE_URL"] = "postgresql+asyncpg://polar:polar@localhost:5432/polar_test"
os.environ["SYNC_ENABLED"] = "false"
os.environ["SYNC_ON_STARTUP"] = "false"
# The test client runs the app in its own event loop (anyio portal); pooled
# asyncpg connections cannot cross loops, so use a fresh connection per use.
os.environ["DATABASE_POOL"] = "null"

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


# =============================================================================
# Analytics Test Data Fixtures
# =============================================================================


@pytest.fixture
async def analytics_user_90d(async_session: AsyncSession, test_user):
    """Create test user with 90 days of analytics data (full baseline status)."""
    from tests.fixtures.analytics_seed import seed_analytics_data

    counts = await seed_analytics_data(
        session=async_session,
        user_id=test_user.polar_user_id,
        days=90,
        include_anomalies=True,
    )
    return test_user, counts


@pytest.fixture
async def analytics_user_21d(async_session: AsyncSession, test_user):
    """Create test user with 21 days of analytics data (ready baseline status)."""
    from tests.fixtures.analytics_seed import seed_analytics_data

    counts = await seed_analytics_data(
        session=async_session,
        user_id=test_user.polar_user_id,
        days=21,
        include_anomalies=False,
    )
    return test_user, counts


@pytest.fixture
async def analytics_user_7d(async_session: AsyncSession, test_user):
    """Create test user with 7 days of analytics data (partial baseline status)."""
    from tests.fixtures.analytics_seed import seed_minimal_data

    counts = await seed_minimal_data(
        session=async_session,
        user_id=test_user.polar_user_id,
        days=7,
    )
    return test_user, counts


@pytest.fixture
async def analytics_user_3d(async_session: AsyncSession, test_user):
    """Create test user with 3 days of analytics data (insufficient baseline status)."""
    from tests.fixtures.analytics_seed import seed_insufficient_data

    counts = await seed_insufficient_data(
        session=async_session,
        user_id=test_user.polar_user_id,
        days=3,
    )
    return test_user, counts


# =============================================================================
# Integration fixtures — the real app (lifespan, middleware, DI) against the
# dedicated polar_test Postgres database. Skipped automatically if Postgres
# is unreachable so unit tests still run anywhere.
# =============================================================================


@pytest.fixture
async def app_client():
    """Full-stack test client: real app with lifespan against polar_test."""
    from litestar.testing import AsyncTestClient
    from sqlalchemy.exc import OperationalError

    import polar_flow_server.models  # noqa: F401 - register all models on Base
    from polar_flow_server.app import create_app
    from polar_flow_server.core.database import engine
    from polar_flow_server.models.base import Base

    # pytest-asyncio gives every test its own event loop, but the app engine
    # is a module-level global — dispose its pool so connections are always
    # created in the current loop (stale ones raise InterfaceError).
    await engine.dispose()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except (OperationalError, OSError) as exc:  # pragma: no cover
        pytest.skip(f"Postgres test database unavailable: {exc}")

    try:
        async with AsyncTestClient(app=create_app()) as client:
            yield client
    finally:
        await engine.dispose()


@pytest.fixture
async def admin_account(app_client):
    """Create an admin user directly in the test database."""
    from polar_flow_server.core.database import async_session_maker
    from polar_flow_server.core.password import hash_password
    from polar_flow_server.models.admin_user import AdminUser

    credentials = {"email": "admin@example.com", "password": "correct-horse-battery"}
    async with async_session_maker() as session:
        session.add(
            AdminUser(
                email=credentials["email"],
                password_hash=hash_password(credentials["password"]),
                is_active=True,
            )
        )
        await session.commit()
    return credentials
