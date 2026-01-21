"""Tests for sync error handling - Issue #19.

Tests that:
1. When Polar API returns 403, the error is captured but sync continues
2. Partial failures allow other endpoints to sync successfully
3. Error messages are user-friendly with actionable guidance
"""

from unittest.mock import AsyncMock, patch

import pytest
from polar_flow.exceptions import PolarFlowError

from polar_flow_server.services.sync import SyncResult, SyncService


@pytest.mark.asyncio
async def test_sync_sleep_403_captured_as_error(async_session):
    """Verify that a 403 from sleep endpoint is captured, not raised."""
    sync_service = SyncService(async_session)

    # Mock the PolarFlow client to raise a 403 error on sleep.list()
    mock_client = AsyncMock()
    mock_client.sleep.list = AsyncMock(
        side_effect=PolarFlowError(
            "API error 403: Forbidden",
            endpoint="/v3/users/sleep",
            status_code=403,
            response_body="Forbidden",
        )
    )
    # Other endpoints succeed
    mock_client.recharge.list = AsyncMock(return_value=[])
    mock_client.activity.list = AsyncMock(return_value=[])
    mock_client.exercises.list = AsyncMock(return_value=[])

    # Mock hasattr checks for optional features
    original_hasattr = hasattr

    def mock_hasattr(obj, name):
        if obj is mock_client and name in (
            "cardio_load",
            "sleepwise",
            "activity_samples",
            "continuous_hr",
            "biosensing",
        ):
            return False
        return original_hasattr(obj, name)

    with patch("polar_flow_server.services.sync.PolarFlow") as MockPolarFlow:
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_client)
        mock_context.__aexit__ = AsyncMock(return_value=None)
        MockPolarFlow.return_value = mock_context

        with patch("builtins.hasattr", mock_hasattr):
            # Should NOT raise - returns SyncResult with error
            result = await sync_service.sync_user(
                user_id="test_user",
                polar_token="fake_token",
                recalculate_baselines=False,
            )

        # Verify result type and error captured
        assert isinstance(result, SyncResult)
        assert result.has_errors
        assert "sleep" in result.errors
        assert "403" in result.errors["sleep"]
        assert "consent" in result.errors["sleep"].lower()


@pytest.mark.asyncio
async def test_sync_continues_after_endpoint_failure(async_session):
    """Verify that if sleep fails with 403, other endpoints still sync."""
    sync_service = SyncService(async_session)

    # Mock client where sleep fails but other endpoints succeed
    mock_client = AsyncMock()
    mock_client.sleep.list = AsyncMock(
        side_effect=PolarFlowError(
            "API error 403: Forbidden",
            endpoint="/v3/users/sleep",
            status_code=403,
            response_body="Forbidden",
        )
    )
    # These should be called and succeed
    mock_client.recharge.list = AsyncMock(return_value=[])
    mock_client.activity.list = AsyncMock(return_value=[])
    mock_client.exercises.list = AsyncMock(return_value=[])

    # Mock hasattr checks for optional features
    original_hasattr = hasattr

    def mock_hasattr(obj, name):
        if obj is mock_client and name in (
            "cardio_load",
            "sleepwise",
            "activity_samples",
            "continuous_hr",
            "biosensing",
        ):
            return False
        return original_hasattr(obj, name)

    with patch("polar_flow_server.services.sync.PolarFlow") as MockPolarFlow:
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_client)
        mock_context.__aexit__ = AsyncMock(return_value=None)
        MockPolarFlow.return_value = mock_context

        with patch("builtins.hasattr", mock_hasattr):
            result = await sync_service.sync_user(
                user_id="test_user",
                polar_token="fake_token",
                recalculate_baselines=False,
            )

        # Verify other endpoints WERE called despite sleep failure
        mock_client.recharge.list.assert_called_once()
        mock_client.activity.list.assert_called_once()
        mock_client.exercises.list.assert_called_once()

        # Sleep has error, others don't
        assert "sleep" in result.errors
        assert "recharge" not in result.errors
        assert "activity" not in result.errors
        assert "exercises" not in result.errors


@pytest.mark.asyncio
async def test_sync_success_returns_counts(async_session):
    """Verify normal sync returns proper counts."""
    sync_service = SyncService(async_session)

    # Mock client with empty but successful responses
    mock_client = AsyncMock()
    mock_client.sleep.list = AsyncMock(return_value=[])
    mock_client.recharge.list = AsyncMock(return_value=[])
    mock_client.activity.list = AsyncMock(return_value=[])
    mock_client.exercises.list = AsyncMock(return_value=[])

    # Mock hasattr checks - these need to return False for optional features
    original_hasattr = hasattr

    def mock_hasattr(obj, name):
        if obj is mock_client and name in (
            "cardio_load",
            "sleepwise",
            "activity_samples",
            "continuous_hr",
            "biosensing",
        ):
            return False
        return original_hasattr(obj, name)

    with patch("polar_flow_server.services.sync.PolarFlow") as MockPolarFlow:
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_client)
        mock_context.__aexit__ = AsyncMock(return_value=None)
        MockPolarFlow.return_value = mock_context

        with patch("builtins.hasattr", mock_hasattr):
            result = await sync_service.sync_user(
                user_id="test_user",
                polar_token="fake_token",
                recalculate_baselines=False,
            )

        # Should return SyncResult with no errors and all zeros (no data synced)
        assert isinstance(result, SyncResult)
        assert not result.has_errors
        assert result.records["sleep"] == 0
        assert result.records["recharge"] == 0
        assert result.records["activity"] == 0
        assert result.records["exercises"] == 0
