"""Biosensing sync errors must reach result.errors (issue #60).

The four biosensing sync methods (and the per-day continuous HR loop) used
to catch *all* exceptions — including 401/403/429 — log at debug, and return
0, so SyncLog recorded 'success' while endpoints were silently failing.

Only NotFoundError (genuinely no data / device doesn't support the endpoint)
may be swallowed now; anything else propagates to sync_user's per-endpoint
handler like the other nine endpoints.
"""

from unittest.mock import AsyncMock, patch

import pytest
from polar_flow.exceptions import (
    AuthenticationError,
    NotFoundError,
    PolarFlowError,
    RateLimitError,
)

from polar_flow_server.services.sync import SyncService


def _mock_client() -> AsyncMock:
    """A client where every endpoint succeeds with no data."""
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


async def _run_sync(async_session, client: AsyncMock):
    sync_service = SyncService(async_session)
    with patch("polar_flow_server.services.sync.PolarFlow") as MockPolarFlow:
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=client)
        mock_context.__aexit__ = AsyncMock(return_value=None)
        MockPolarFlow.return_value = mock_context
        return await sync_service.sync_user(
            user_id="test_user",
            polar_token="fake_token",
            recalculate_baselines=False,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sdk_method", "endpoint"),
    [
        ("get_spo2", "spo2"),
        ("get_ecg", "ecg"),
        ("get_body_temperature", "body_temperature"),
        ("get_skin_temperature", "skin_temperature"),
    ],
)
async def test_auth_error_reaches_result_errors(async_session, sdk_method, endpoint):
    """A 403 is a real failure — it must not be logged away as 'skipped'."""
    client = _mock_client()
    setattr(
        client.biosensing,
        sdk_method,
        AsyncMock(
            side_effect=AuthenticationError(
                "API error 403: Forbidden", status_code=403, endpoint=f"/v3/{endpoint}"
            )
        ),
    )

    result = await _run_sync(async_session, client)

    assert endpoint in result.errors
    # The rest of the sync still completed
    assert result.records["sleep"] == 0
    assert "sleep" not in result.errors


@pytest.mark.asyncio
async def test_rate_limit_error_reaches_result_errors(async_session):
    client = _mock_client()
    client.biosensing.get_ecg = AsyncMock(
        side_effect=RateLimitError("API error 429: Too Many Requests", retry_after=60)
    )

    result = await _run_sync(async_session, client)

    assert "ecg" in result.errors
    assert "spo2" not in result.errors


@pytest.mark.asyncio
async def test_not_found_is_still_swallowed(async_session):
    """No data / unsupported device stays a quiet skip, not an error."""
    client = _mock_client()
    client.biosensing.get_spo2 = AsyncMock(
        side_effect=NotFoundError("API error 404: Not Found", status_code=404)
    )

    result = await _run_sync(async_session, client)

    assert result.errors == {}
    assert result.records["spo2"] == 0


@pytest.mark.asyncio
async def test_continuous_hr_real_error_propagates(async_session):
    """A real API error mid-loop must fail the endpoint, not skip the day."""
    client = _mock_client()
    client.continuous_hr.get = AsyncMock(
        side_effect=PolarFlowError("API error 500: Server Error", status_code=500)
    )

    result = await _run_sync(async_session, client)

    assert "continuous_hr" in result.errors


@pytest.mark.asyncio
async def test_continuous_hr_not_found_day_is_skipped(async_session):
    """Days with no recording keep the loop going and stay off the errors."""
    client = _mock_client()
    client.continuous_hr.get = AsyncMock(
        side_effect=NotFoundError("API error 404: Not Found", status_code=404)
    )

    result = await _run_sync(async_session, client)

    assert "continuous_hr" not in result.errors
    assert result.records["continuous_hr"] == 0
