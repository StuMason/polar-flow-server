"""A database error in one endpoint must not sink the rest of the sync (issue #144).

On Postgres a failed statement aborts the whole transaction. Before each
endpoint ran in a savepoint, one bad insert failed every later endpoint
and the final commit rolled back the sync log, which surfaced as the
misleading "UPDATE statement on table 'sync_logs' expected to update 1
row(s); 0 were matched". SQLite doesn't abort the transaction, so this
needs the Postgres test database.
"""

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import polar_flow_server.models  # noqa: F401 - register all models on Base
from polar_flow_server.models.base import Base
from polar_flow_server.models.temperature import BodyTemperature
from tests.test_biosensing_error_propagation import _mock_client, _run_sync


@pytest.fixture
async def pg_session():
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except (OperationalError, OSError) as exc:  # pragma: no cover
        await engine.dispose()
        pytest.skip(f"Postgres test database unavailable: {exc}")

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session, session_maker
    await engine.dispose()


@pytest.mark.asyncio
async def test_db_error_in_one_endpoint_keeps_the_others(pg_session, monkeypatch):
    session, session_maker = pg_session

    async def broken_sleep(self, client, user_id, days=None):
        await self.session.execute(text("SELECT 1/0"))
        return 0

    async def working_recharge(self, client, user_id):
        self.session.add(
            BodyTemperature(
                user_id=user_id,
                device_id="d",
                start_time=datetime(2026, 10, 1, tzinfo=UTC),
                end_time=datetime(2026, 10, 1, 1, tzinfo=UTC),
                measurement_type="CONTINUOUS",
                sensor_location="WRIST",
            )
        )
        await self.session.flush()
        return 1

    from polar_flow_server.services.sync import SyncService

    monkeypatch.setattr(SyncService, "_sync_sleep", broken_sleep)
    monkeypatch.setattr(SyncService, "_sync_recharge", working_recharge)

    result = await _run_sync(session, _mock_client())

    assert set(result.errors) == {"sleep"}
    assert result.records["recharge"] == 1
    async with session_maker() as fresh:
        saved = await fresh.scalar(select(func.count()).select_from(BodyTemperature))
    assert saved == 1, "the working endpoint's write was committed"
