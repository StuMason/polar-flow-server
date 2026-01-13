"""Tests for baseline analytics functionality."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.models.baseline import BaselineStatus, MetricName
from polar_flow_server.services.baseline import BaselineService


class TestBaselineService:
    """Tests for BaselineService."""

    @pytest.mark.asyncio
    async def test_calculate_hrv_baseline_with_90d_data(
        self, async_session: AsyncSession, analytics_user_90d
    ):
        """Test HRV baseline calculation with 90 days of data returns 'ready' status."""
        user, counts = analytics_user_90d
        service = BaselineService(async_session)

        status = await service.calculate_hrv_baseline(user.polar_user_id)

        assert status == BaselineStatus.READY.value
        assert counts["recharge"] == 90  # Verify data was seeded

    @pytest.mark.asyncio
    async def test_calculate_hrv_baseline_with_21d_data(
        self, async_session: AsyncSession, analytics_user_21d
    ):
        """Test HRV baseline calculation with 21 days returns 'ready' status."""
        user, counts = analytics_user_21d
        service = BaselineService(async_session)

        status = await service.calculate_hrv_baseline(user.polar_user_id)

        assert status == BaselineStatus.READY.value

    @pytest.mark.asyncio
    async def test_calculate_hrv_baseline_with_7d_data(
        self, async_session: AsyncSession, analytics_user_7d
    ):
        """Test HRV baseline calculation with 7 days returns 'partial' status."""
        user, counts = analytics_user_7d
        service = BaselineService(async_session)

        status = await service.calculate_hrv_baseline(user.polar_user_id)

        assert status == BaselineStatus.PARTIAL.value

    @pytest.mark.asyncio
    async def test_calculate_hrv_baseline_with_3d_data(
        self, async_session: AsyncSession, analytics_user_3d
    ):
        """Test HRV baseline calculation with 3 days returns 'insufficient' status."""
        user, counts = analytics_user_3d
        service = BaselineService(async_session)

        status = await service.calculate_hrv_baseline(user.polar_user_id)

        assert status == BaselineStatus.INSUFFICIENT.value

    @pytest.mark.asyncio
    async def test_calculate_all_baselines(self, async_session: AsyncSession, analytics_user_90d):
        """Test calculating all baselines at once."""
        user, _ = analytics_user_90d
        service = BaselineService(async_session)

        results = await service.calculate_all_baselines(user.polar_user_id)

        # All metrics should be calculated
        assert MetricName.HRV_RMSSD.value in results
        assert MetricName.SLEEP_SCORE.value in results
        assert MetricName.RESTING_HR.value in results
        assert MetricName.TRAINING_LOAD.value in results
        assert MetricName.TRAINING_LOAD_RATIO.value in results

        # With 90 days, HRV, sleep, and resting HR should be ready
        assert results[MetricName.HRV_RMSSD.value] == BaselineStatus.READY.value
        assert results[MetricName.SLEEP_SCORE.value] == BaselineStatus.READY.value
        assert results[MetricName.RESTING_HR.value] == BaselineStatus.READY.value

    @pytest.mark.asyncio
    async def test_get_baseline_returns_statistics(
        self, async_session: AsyncSession, analytics_user_90d
    ):
        """Test that baseline includes all expected statistics."""
        user, _ = analytics_user_90d
        service = BaselineService(async_session)

        # First calculate
        await service.calculate_all_baselines(user.polar_user_id)

        # Then retrieve
        baseline = await service.get_baseline(user.polar_user_id, MetricName.HRV_RMSSD)

        assert baseline is not None
        assert baseline.baseline_value > 0
        assert baseline.baseline_7d is not None
        assert baseline.baseline_30d is not None
        assert baseline.baseline_90d is not None
        assert baseline.median_value is not None
        assert baseline.q1 is not None
        assert baseline.q3 is not None
        assert baseline.std_dev is not None
        assert baseline.min_value is not None
        assert baseline.max_value is not None
        assert baseline.sample_count == 90

    @pytest.mark.asyncio
    async def test_baseline_iqr_calculation(self, async_session: AsyncSession, analytics_user_90d):
        """Test IQR and bounds are calculated correctly."""
        user, _ = analytics_user_90d
        service = BaselineService(async_session)

        await service.calculate_all_baselines(user.polar_user_id)
        baseline = await service.get_baseline(user.polar_user_id, MetricName.HRV_RMSSD)

        assert baseline is not None
        assert baseline.iqr is not None
        assert baseline.iqr == baseline.q3 - baseline.q1
        assert baseline.lower_bound == baseline.q1 - 1.5 * baseline.iqr
        assert baseline.upper_bound == baseline.q3 + 1.5 * baseline.iqr

    @pytest.mark.asyncio
    async def test_anomaly_detection_normal_value(
        self, async_session: AsyncSession, analytics_user_90d
    ):
        """Test that normal values are not flagged as anomalies."""
        user, _ = analytics_user_90d
        service = BaselineService(async_session)

        await service.calculate_all_baselines(user.polar_user_id)
        baseline = await service.get_baseline(user.polar_user_id, MetricName.HRV_RMSSD)

        # Test with the median value (should not be anomaly)
        is_anomaly, severity = baseline.is_anomaly(baseline.median_value)

        assert is_anomaly is False
        assert severity is None

    @pytest.mark.asyncio
    async def test_anomaly_detection_warning(self, async_session: AsyncSession, analytics_user_90d):
        """Test that values outside 1.5*IQR are flagged as warnings."""
        user, _ = analytics_user_90d
        service = BaselineService(async_session)

        await service.calculate_all_baselines(user.polar_user_id)
        baseline = await service.get_baseline(user.polar_user_id, MetricName.HRV_RMSSD)

        # Test with value just below lower bound
        low_value = baseline.lower_bound - 1

        is_anomaly, severity = baseline.is_anomaly(low_value)

        assert is_anomaly is True
        assert severity == "warning"

    @pytest.mark.asyncio
    async def test_anomaly_detection_critical(
        self, async_session: AsyncSession, analytics_user_90d
    ):
        """Test that values outside 3*IQR are flagged as critical."""
        user, _ = analytics_user_90d
        service = BaselineService(async_session)

        await service.calculate_all_baselines(user.polar_user_id)
        baseline = await service.get_baseline(user.polar_user_id, MetricName.HRV_RMSSD)

        # Test with value way below extreme lower bound
        extreme_low = baseline.q1 - 4 * baseline.iqr

        is_anomaly, severity = baseline.is_anomaly(extreme_low)

        assert is_anomaly is True
        assert severity == "critical"

    @pytest.mark.asyncio
    async def test_get_user_baselines_returns_all(
        self, async_session: AsyncSession, analytics_user_90d
    ):
        """Test getting all baselines for a user."""
        user, _ = analytics_user_90d
        service = BaselineService(async_session)

        await service.calculate_all_baselines(user.polar_user_id)
        baselines = await service.get_user_baselines(user.polar_user_id)

        # Should have 5 metrics (the ones currently implemented)
        assert len(baselines) == 5

        # Verify all implemented metrics are present
        metric_names = {b.metric_name for b in baselines}
        expected_metrics = {
            MetricName.HRV_RMSSD.value,
            MetricName.SLEEP_SCORE.value,
            MetricName.RESTING_HR.value,
            MetricName.TRAINING_LOAD.value,
            MetricName.TRAINING_LOAD_RATIO.value,
        }
        assert metric_names == expected_metrics

    @pytest.mark.asyncio
    async def test_baseline_recalculation_updates_values(
        self, async_session: AsyncSession, analytics_user_21d
    ):
        """Test that recalculating baselines updates the values."""
        user, _ = analytics_user_21d
        service = BaselineService(async_session)

        # Calculate first time
        await service.calculate_all_baselines(user.polar_user_id)
        baseline1 = await service.get_baseline(user.polar_user_id, MetricName.HRV_RMSSD)

        # Calculate again
        await service.calculate_all_baselines(user.polar_user_id)
        baseline2 = await service.get_baseline(user.polar_user_id, MetricName.HRV_RMSSD)

        # Same baseline value (data hasn't changed)
        assert baseline1.baseline_value == baseline2.baseline_value
        # But updated_at should be different (or same if within same second)
        assert baseline2.id == baseline1.id  # Same record, upserted

    @pytest.mark.asyncio
    async def test_empty_user_returns_insufficient(self, async_session: AsyncSession, test_user):
        """Test that a user with no data returns insufficient status."""
        service = BaselineService(async_session)

        status = await service.calculate_hrv_baseline(test_user.polar_user_id)

        assert status == BaselineStatus.INSUFFICIENT.value
