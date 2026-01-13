"""Tests for pattern detection service."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.models.baseline import MetricName, UserBaseline
from polar_flow_server.models.cardio_load import CardioLoad
from polar_flow_server.models.pattern import PatternName, PatternType, Significance
from polar_flow_server.models.recharge import NightlyRecharge
from polar_flow_server.models.sleep import Sleep
from polar_flow_server.services.pattern import AnomalyService, PatternResult, PatternService


class TestPatternResult:
    """Tests for PatternResult dataclass."""

    def test_pattern_result_defaults(self) -> None:
        """Test PatternResult has correct defaults."""
        result = PatternResult(
            pattern_type=PatternType.CORRELATION.value,
            pattern_name=PatternName.SLEEP_HRV_CORRELATION.value,
        )
        assert result.score is None
        assert result.confidence is None
        assert result.significance == Significance.INSUFFICIENT.value
        assert result.sample_count == 0

    def test_pattern_result_with_values(self) -> None:
        """Test PatternResult with full values."""
        result = PatternResult(
            pattern_type=PatternType.CORRELATION.value,
            pattern_name=PatternName.SLEEP_HRV_CORRELATION.value,
            score=0.65,
            confidence=0.98,
            significance=Significance.HIGH.value,
            sample_count=45,
            metrics_involved=["sleep_score", "hrv_rmssd"],
            details={"interpretation": "Strong positive correlation"},
        )
        assert result.score == 0.65
        assert result.confidence == 0.98
        assert result.significance == Significance.HIGH.value
        assert result.sample_count == 45
        assert result.metrics_involved == ["sleep_score", "hrv_rmssd"]


class TestPatternService:
    """Tests for PatternService."""

    @pytest.fixture
    async def seeded_correlation_data(self, async_session: AsyncSession) -> str:
        """Seed 30 days of correlated sleep and HRV data."""
        user_id = "correlation-test-user"
        today = datetime.now(UTC).date()

        # Create correlated data: high sleep -> high HRV
        for i in range(30):
            date = today - timedelta(days=i)
            base_sleep = 70 + (i % 10) * 2  # Varies 70-88
            base_hrv = 35 + (i % 10) * 1.5  # Correlates with sleep

            # Add sleep record
            sleep = Sleep(
                user_id=user_id,
                date=date,
                sleep_start_time=datetime.combine(date, datetime.min.time()),
                sleep_end_time=datetime.combine(date, datetime.min.time()) + timedelta(hours=8),
                sleep_score=base_sleep,
            )
            async_session.add(sleep)

            # Add recharge record with HRV
            recharge = NightlyRecharge(
                user_id=user_id,
                date=date,
                hrv_avg=base_hrv,
                ans_charge=3.5,
                ans_charge_status="WELL_RECOVERED",
                heart_rate_avg=55 + (i % 5),
            )
            async_session.add(recharge)

        await async_session.commit()
        return user_id

    @pytest.fixture
    async def seeded_overtraining_data(self, async_session: AsyncSession) -> str:
        """Seed data that triggers overtraining risk."""
        user_id = "overtraining-test-user"
        today = datetime.now(UTC).date()

        # Create declining metrics (signs of overtraining)
        for i in range(30):
            date = today - timedelta(days=i)

            # Recent days (0-6): declining HRV and sleep
            if i < 7:
                hrv = 30 - i * 2  # Declining HRV
                sleep_score = 60 - i * 3  # Declining sleep
                hr = 65 + i * 2  # Increasing RHR
            else:
                hrv = 45  # Baseline HRV
                sleep_score = 80  # Baseline sleep
                hr = 55  # Baseline RHR

            sleep = Sleep(
                user_id=user_id,
                date=date,
                sleep_start_time=datetime.combine(date, datetime.min.time()),
                sleep_end_time=datetime.combine(date, datetime.min.time()) + timedelta(hours=7),
                sleep_score=sleep_score,
            )
            async_session.add(sleep)

            recharge = NightlyRecharge(
                user_id=user_id,
                date=date,
                hrv_avg=hrv,
                ans_charge=3.0,
                ans_charge_status="MODERATELY_RECOVERED",
                heart_rate_avg=hr,
            )
            async_session.add(recharge)

        # Add high training load ratio
        cardio = CardioLoad(
            user_id=user_id,
            date=today,
            cardio_load=150.0,
            cardio_load_ratio=1.8,  # High ratio (overtraining signal)
        )
        async_session.add(cardio)

        await async_session.commit()
        return user_id

    @pytest.mark.asyncio
    async def test_detect_sleep_hrv_correlation_with_data(
        self, async_session: AsyncSession, seeded_correlation_data: str
    ) -> None:
        """Test correlation detection with sufficient data."""
        user_id = seeded_correlation_data
        service = PatternService(async_session)

        result = await service.detect_sleep_hrv_correlation(user_id)

        assert result.pattern_type == PatternType.CORRELATION.value
        assert result.pattern_name == PatternName.SLEEP_HRV_CORRELATION.value
        assert result.score is not None
        assert result.score > 0.3  # Should show positive correlation
        assert result.significance in [Significance.HIGH.value, Significance.MEDIUM.value]
        assert result.sample_count >= 21
        assert result.details is not None
        assert "correlation_coefficient" in result.details

    @pytest.mark.asyncio
    async def test_detect_sleep_hrv_correlation_insufficient_data(
        self, async_session: AsyncSession
    ) -> None:
        """Test correlation detection with insufficient data."""
        user_id = "no-data-user"
        service = PatternService(async_session)

        result = await service.detect_sleep_hrv_correlation(user_id)

        assert result.significance == Significance.INSUFFICIENT.value
        assert result.sample_count < 21

    @pytest.mark.asyncio
    async def test_detect_overtraining_risk_elevated(
        self, async_session: AsyncSession, seeded_overtraining_data: str
    ) -> None:
        """Test overtraining risk detection with concerning metrics."""
        user_id = seeded_overtraining_data
        service = PatternService(async_session)

        result = await service.detect_overtraining_risk(user_id)

        assert result.pattern_type == PatternType.COMPOSITE.value
        assert result.pattern_name == PatternName.OVERTRAINING_RISK.value
        assert result.score is not None
        assert result.score >= 25  # Should detect some risk
        assert result.details is not None
        assert "risk_factors" in result.details
        assert len(result.details["risk_factors"]) > 0
        assert "recommendations" in result.details

    @pytest.mark.asyncio
    async def test_detect_all_patterns(
        self, async_session: AsyncSession, seeded_correlation_data: str
    ) -> None:
        """Test detecting all patterns at once."""
        user_id = seeded_correlation_data
        service = PatternService(async_session)

        results = await service.detect_all_patterns(user_id)

        assert PatternName.SLEEP_HRV_CORRELATION.value in results
        assert PatternName.OVERTRAINING_RISK.value in results
        assert PatternName.HRV_TREND.value in results
        assert PatternName.SLEEP_TREND.value in results

    @pytest.mark.asyncio
    async def test_get_user_patterns_after_detection(
        self, async_session: AsyncSession, seeded_correlation_data: str
    ) -> None:
        """Test retrieving patterns after detection."""
        user_id = seeded_correlation_data
        service = PatternService(async_session)

        # First detect patterns
        await service.detect_all_patterns(user_id)

        # Then retrieve them
        patterns = await service.get_user_patterns(user_id)

        assert len(patterns) >= 4
        pattern_names = [p.pattern_name for p in patterns]
        assert PatternName.SLEEP_HRV_CORRELATION.value in pattern_names

    @pytest.mark.asyncio
    async def test_get_specific_pattern(
        self, async_session: AsyncSession, seeded_correlation_data: str
    ) -> None:
        """Test retrieving a specific pattern by name."""
        user_id = seeded_correlation_data
        service = PatternService(async_session)

        # First detect patterns
        await service.detect_all_patterns(user_id)

        # Get specific pattern
        pattern = await service.get_pattern(user_id, PatternName.SLEEP_HRV_CORRELATION.value)

        assert pattern is not None
        assert pattern.pattern_name == PatternName.SLEEP_HRV_CORRELATION.value
        assert pattern.score is not None


class TestAnomalyService:
    """Tests for AnomalyService."""

    @pytest.fixture
    async def seeded_baseline_with_anomaly(self, async_session: AsyncSession) -> tuple[str, float]:
        """Seed baseline and return user_id and anomalous value."""
        user_id = "anomaly-test-user"

        # Create baseline with known bounds
        baseline = UserBaseline(
            user_id=user_id,
            metric_name=MetricName.HRV_RMSSD.value,
            baseline_value=45.0,
            baseline_7d=46.0,
            q1=40.0,  # Q1
            q3=50.0,  # Q3, so IQR = 10
            median_value=45.0,
            sample_count=30,
            status="ready",
            calculated_at=datetime.now(UTC),
        )
        # lower_bound = 40 - 1.5*10 = 25
        # upper_bound = 50 + 1.5*10 = 65
        async_session.add(baseline)

        # Add recent HRV that is anomalous (below lower bound)
        recharge = NightlyRecharge(
            user_id=user_id,
            date=datetime.now(UTC).date(),
            hrv_avg=20.0,  # Below lower_bound of 25
            ans_charge=2.0,
            ans_charge_status="NOT_RECOVERED",
            heart_rate_avg=65,
        )
        async_session.add(recharge)

        await async_session.commit()
        return user_id, 20.0

    @pytest.mark.asyncio
    async def test_detect_anomaly(
        self, async_session: AsyncSession, seeded_baseline_with_anomaly: tuple[str, float]
    ) -> None:
        """Test anomaly detection finds values outside bounds."""
        user_id, anomalous_value = seeded_baseline_with_anomaly
        service = AnomalyService(async_session)

        anomalies = await service.detect_all_anomalies(user_id)

        assert len(anomalies) >= 1
        hrv_anomaly = next((a for a in anomalies if a["metric_name"] == "hrv_rmssd"), None)
        assert hrv_anomaly is not None
        assert hrv_anomaly["current_value"] == anomalous_value
        assert hrv_anomaly["severity"] == "warning"
        assert hrv_anomaly["direction"] == "below"

    @pytest.mark.asyncio
    async def test_no_anomalies_when_no_baselines(self, async_session: AsyncSession) -> None:
        """Test no anomalies returned when no baselines exist."""
        user_id = "no-baseline-user"
        service = AnomalyService(async_session)

        anomalies = await service.detect_all_anomalies(user_id)

        assert len(anomalies) == 0


class TestRecoveryRecommendations:
    """Tests for recovery recommendations generation."""

    def test_high_risk_recommendations(self) -> None:
        """Test recommendations for high risk score."""
        service = PatternService.__new__(PatternService)
        recs = service._get_recovery_recommendations(80, ["HRV declining", "Sleep declining"])

        assert len(recs) >= 3
        assert any("rest day" in r.lower() for r in recs)
        assert any("sleep" in r.lower() for r in recs)

    def test_medium_risk_recommendations(self) -> None:
        """Test recommendations for medium risk score."""
        service = PatternService.__new__(PatternService)
        recs = service._get_recovery_recommendations(50, ["HRV declining"])

        assert len(recs) >= 2
        assert any("intensity" in r.lower() for r in recs)

    def test_low_risk_recommendations(self) -> None:
        """Test recommendations for low risk score."""
        service = PatternService.__new__(PatternService)
        recs = service._get_recovery_recommendations(10, [])

        assert len(recs) >= 1
        assert any("manageable" in r.lower() for r in recs)
