"""Rate-limit tracking and transient retry tests (issue #64).

Before this, RateLimitTracker.can_sync_now() always returned True (nothing
ever fed it), SyncErrorHandler's is_transient/retry_after were computed but
never consumed, and any 429 or API blip simply failed the endpoint.

Now: transient failures (5xx/timeouts) get a single short-backoff retry,
429s feed a process-wide backoff window that the scheduler honours, and
the Retry-After value is respected rather than hammered.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from polar_flow.exceptions import AuthenticationError, PolarFlowError, RateLimitError

from polar_flow_server.services.sync import SyncResult, SyncService
from polar_flow_server.services.sync_orchestrator import (
    RateLimitTracker,
    SyncOrchestrator,
    shared_rate_limit_tracker,
)


@pytest.fixture(autouse=True)
def _clean_shared_tracker():
    shared_rate_limit_tracker.rate_limited_until = None
    yield
    shared_rate_limit_tracker.rate_limited_until = None


def _mock_client() -> AsyncMock:
    client = AsyncMock()
    client.sleep.list = AsyncMock(return_value=[])
    client.recharge.list = AsyncMock(return_value=[])
    client.activity.list = AsyncMock(return_value=[])
    client.exercises.list = AsyncMock(return_value=[])
    client.cardio_load.list = AsyncMock(return_value=[])
    client.sleepwise.get_alertness = AsyncMock(return_value=[])
    client.sleepwise.get_bedtime = AsyncMock(return_value=[])
    client.activity_samples.list = AsyncMock(return_value=[])
    client.continuous_hr.get = AsyncMock(return_value=None)
    client.biosensing.get_spo2 = AsyncMock(return_value=[])
    client.biosensing.get_ecg = AsyncMock(return_value=[])
    client.biosensing.get_body_temperature = AsyncMock(return_value=[])
    client.biosensing.get_skin_temperature = AsyncMock(return_value=[])
    return client


async def _run_sync(async_session, client: AsyncMock) -> SyncResult:
    sync_service = SyncService(async_session)
    with (
        patch("polar_flow_server.services.sync.PolarFlow") as MockPolarFlow,
        patch("polar_flow_server.services.sync.asyncio.sleep", AsyncMock()),
    ):
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=client)
        mock_context.__aexit__ = AsyncMock(return_value=None)
        MockPolarFlow.return_value = mock_context
        return await sync_service.sync_user(
            user_id="test_user",
            polar_token="fake_token",
            recalculate_baselines=False,
        )


class TestTransientRetry:
    @pytest.mark.asyncio
    async def test_transient_500_is_retried_once_and_recovers(self, async_session):
        client = _mock_client()
        client.sleep.list = AsyncMock(
            side_effect=[
                PolarFlowError("API error 500: Server Error", status_code=500),
                [],
            ]
        )

        result = await _run_sync(async_session, client)

        assert client.sleep.list.call_count == 2
        assert "sleep" not in result.errors

    @pytest.mark.asyncio
    async def test_persistent_500_fails_after_one_retry(self, async_session):
        client = _mock_client()
        client.sleep.list = AsyncMock(
            side_effect=PolarFlowError("API error 500: Server Error", status_code=500)
        )

        result = await _run_sync(async_session, client)

        assert client.sleep.list.call_count == 2
        assert "sleep" in result.errors

    @pytest.mark.asyncio
    async def test_non_transient_403_is_not_retried(self, async_session):
        client = _mock_client()
        client.sleep.list = AsyncMock(
            side_effect=AuthenticationError("API error 403: Forbidden", status_code=403)
        )

        result = await _run_sync(async_session, client)

        assert client.sleep.list.call_count == 1
        assert "sleep" in result.errors

    @pytest.mark.asyncio
    async def test_429_is_not_retried_and_records_backoff(self, async_session):
        """Retry-After windows are minutes long — hammering is the wrong
        move. The 429 is recorded so the orchestrator can back off."""
        client = _mock_client()
        client.sleep.list = AsyncMock(side_effect=RateLimitError("API error 429", retry_after=120))

        result = await _run_sync(async_session, client)

        assert client.sleep.list.call_count == 1
        assert "sleep" in result.errors
        assert result.rate_limited_for == 120

    @pytest.mark.asyncio
    async def test_worst_retry_after_wins(self, async_session):
        client = _mock_client()
        client.sleep.list = AsyncMock(side_effect=RateLimitError("429", retry_after=60))
        client.activity.list = AsyncMock(side_effect=RateLimitError("429", retry_after=900))

        result = await _run_sync(async_session, client)

        assert result.rate_limited_for == 900


class TestRateLimitTracker:
    def test_note_rate_limited_blocks_syncs(self):
        tracker = RateLimitTracker()
        assert tracker.can_sync_now()

        tracker.note_rate_limited(300)

        assert not tracker.can_sync_now()
        assert 0 < tracker.get_wait_time_seconds() <= 301

    def test_cooldown_expires(self):
        tracker = RateLimitTracker()
        tracker.rate_limited_until = datetime.now(UTC) - timedelta(seconds=1)

        assert tracker.can_sync_now()
        assert tracker.rate_limited_until is None

    def test_longer_window_is_kept(self):
        tracker = RateLimitTracker()
        tracker.note_rate_limited(600)
        first = tracker.rate_limited_until
        tracker.note_rate_limited(60)

        assert tracker.rate_limited_until == first

    @pytest.mark.asyncio
    async def test_scheduler_cycle_skips_during_cooldown(self, async_session):
        """process_sync_queue's can_sync_now() gate is finally reachable."""
        shared_rate_limit_tracker.note_rate_limited(300)
        orchestrator = SyncOrchestrator(async_session)

        results = await orchestrator.process_sync_queue()

        assert results == []


class TestOrchestratorFeedsTracker:
    @pytest.mark.asyncio
    async def test_429_during_sync_sets_shared_backoff(self, app_client):
        """A rate-limited sync must arm the shared tracker for the next
        cycle (postgres-backed: SyncLog timestamps need tz-aware storage)."""
        from polar_flow_server.core.database import async_session_maker

        async with async_session_maker() as session:
            orchestrator = SyncOrchestrator(session)
            with patch.object(
                orchestrator.sync_service,
                "sync_user",
                AsyncMock(
                    return_value=SyncResult(
                        records={"sleep": 0},
                        errors={"sleep": "Rate limited"},
                        rate_limited_for=120,
                    )
                ),
            ):
                await orchestrator.sync_user(user_id="user-a", polar_token="fake")

        assert shared_rate_limit_tracker.rate_limited_until is not None
        assert not shared_rate_limit_tracker.can_sync_now()
