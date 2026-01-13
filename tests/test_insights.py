"""Tests for insights service and API."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.models.baseline import MetricName, UserBaseline
from polar_flow_server.models.pattern import PatternAnalysis, PatternName, PatternType, Significance
from polar_flow_server.models.recharge import NightlyRecharge
from polar_flow_server.models.sleep import Sleep
from polar_flow_server.schemas.insights import (
    InsightStatus,
    ObservationCategory,
    ObservationPriority,
)
from polar_flow_server.services.insights import UNLOCK_THRESHOLDS, InsightsService
from polar_flow_server.services.observations import ObservationGenerator


class TestInsightsService:
    """Tests for InsightsService."""

    @pytest.fixture
    async def user_no_data(self) -> str:
        """User with no data."""
        return "no-data-user"

    @pytest.fixture
    async def user_7_days(self, async_session: AsyncSession) -> str:
        """User with 7 days of data."""
        user_id = "user-7-days"
        today = datetime.now(UTC).date()

        for i in range(7):
            date = today - timedelta(days=i)
            sleep = Sleep(
                user_id=user_id,
                date=date,
                sleep_start_time=datetime.combine(date, datetime.min.time()),
                sleep_end_time=datetime.combine(date, datetime.min.time()) + timedelta(hours=7),
                sleep_score=75 + i,
            )
            async_session.add(sleep)

            recharge = NightlyRecharge(
                user_id=user_id,
                date=date,
                hrv_avg=45.0 + i,
                ans_charge=3.5,
                ans_charge_status="MODERATELY_RECOVERED",
                heart_rate_avg=55,
            )
            async_session.add(recharge)

        await async_session.commit()
        return user_id

    @pytest.fixture
    async def user_30_days(self, async_session: AsyncSession) -> str:
        """User with 30 days of data."""
        user_id = "user-30-days"
        today = datetime.now(UTC).date()

        for i in range(30):
            date = today - timedelta(days=i)
            sleep = Sleep(
                user_id=user_id,
                date=date,
                sleep_start_time=datetime.combine(date, datetime.min.time()),
                sleep_end_time=datetime.combine(date, datetime.min.time()) + timedelta(hours=7),
                sleep_score=75 + (i % 10),
            )
            async_session.add(sleep)

            recharge = NightlyRecharge(
                user_id=user_id,
                date=date,
                hrv_avg=45.0 + (i % 8),
                ans_charge=3.5,
                ans_charge_status="MODERATELY_RECOVERED",
                heart_rate_avg=55 + (i % 5),
            )
            async_session.add(recharge)

        # Add baselines for this user
        hrv_baseline = UserBaseline(
            user_id=user_id,
            metric_name=MetricName.HRV_RMSSD.value,
            baseline_value=48.0,
            baseline_7d=49.0,
            baseline_30d=48.0,
            q1=42.0,
            q3=54.0,
            median_value=48.0,
            sample_count=30,
            status="ready",
            calculated_at=datetime.now(UTC),
        )
        async_session.add(hrv_baseline)

        sleep_baseline = UserBaseline(
            user_id=user_id,
            metric_name=MetricName.SLEEP_SCORE.value,
            baseline_value=78.0,
            baseline_7d=79.0,
            baseline_30d=78.0,
            q1=72.0,
            q3=84.0,
            median_value=78.0,
            sample_count=30,
            status="ready",
            calculated_at=datetime.now(UTC),
        )
        async_session.add(sleep_baseline)

        await async_session.commit()
        return user_id

    @pytest.fixture
    async def user_with_patterns(self, async_session: AsyncSession, user_30_days: str) -> str:
        """User with detected patterns."""
        user_id = user_30_days

        # Add pattern analyses
        correlation = PatternAnalysis(
            user_id=user_id,
            pattern_type=PatternType.CORRELATION.value,
            pattern_name=PatternName.SLEEP_HRV_CORRELATION.value,
            score=0.65,
            confidence=0.95,
            significance=Significance.HIGH.value,
            sample_count=30,
            metrics_involved=["sleep_score", "hrv_rmssd"],
            details={
                "correlation_coefficient": 0.65,
                "p_value": 0.01,
                "interpretation": "Strong positive correlation",
            },
            analyzed_at=datetime.now(UTC),
        )
        async_session.add(correlation)

        overtraining = PatternAnalysis(
            user_id=user_id,
            pattern_type=PatternType.COMPOSITE.value,
            pattern_name=PatternName.OVERTRAINING_RISK.value,
            score=35.0,
            confidence=0.8,
            significance=Significance.MEDIUM.value,
            sample_count=7,
            metrics_involved=["hrv_rmssd", "sleep_score", "resting_hr"],
            details={
                "risk_factors": ["HRV trending slightly below baseline"],
                "recommendations": ["Monitor your body's response to training"],
            },
            analyzed_at=datetime.now(UTC),
        )
        async_session.add(overtraining)

        await async_session.commit()
        return user_id

    @pytest.mark.asyncio
    async def test_no_data_returns_unavailable(
        self, async_session: AsyncSession, user_no_data: str
    ) -> None:
        """Test that user with no data gets unavailable status."""
        service = InsightsService(async_session)
        insights = await service.get_insights(user_no_data)

        assert insights.status == InsightStatus.UNAVAILABLE
        assert insights.data_age_days == 0
        assert not insights.feature_availability.baselines_7d.available
        assert not insights.feature_availability.patterns.available

    @pytest.mark.asyncio
    async def test_7_days_returns_partial(
        self, async_session: AsyncSession, user_7_days: str
    ) -> None:
        """Test that user with 7 days gets partial status."""
        service = InsightsService(async_session)
        insights = await service.get_insights(user_7_days)

        assert insights.status == InsightStatus.PARTIAL
        assert insights.data_age_days >= 7
        assert insights.feature_availability.baselines_7d.available
        assert not insights.feature_availability.baselines_30d.available
        assert not insights.feature_availability.patterns.available

    @pytest.mark.asyncio
    async def test_30_days_returns_ready(
        self, async_session: AsyncSession, user_30_days: str
    ) -> None:
        """Test that user with 30 days gets ready status."""
        service = InsightsService(async_session)
        insights = await service.get_insights(user_30_days)

        assert insights.status == InsightStatus.READY
        assert insights.data_age_days >= 30
        assert insights.feature_availability.baselines_7d.available
        assert insights.feature_availability.baselines_30d.available
        assert insights.feature_availability.patterns.available
        assert insights.feature_availability.anomaly_detection.available
        assert not insights.feature_availability.ml_predictions.available

    @pytest.mark.asyncio
    async def test_current_metrics_populated(
        self, async_session: AsyncSession, user_30_days: str
    ) -> None:
        """Test that current metrics are populated."""
        service = InsightsService(async_session)
        insights = await service.get_insights(user_30_days)

        assert insights.current_metrics.hrv is not None
        assert insights.current_metrics.sleep_score is not None

    @pytest.mark.asyncio
    async def test_baselines_included(self, async_session: AsyncSession, user_30_days: str) -> None:
        """Test that baselines are included in response."""
        service = InsightsService(async_session)
        insights = await service.get_insights(user_30_days)

        assert "hrv_rmssd" in insights.baselines
        assert "sleep_score" in insights.baselines
        assert insights.baselines["hrv_rmssd"].baseline is not None

    @pytest.mark.asyncio
    async def test_patterns_included(
        self, async_session: AsyncSession, user_with_patterns: str
    ) -> None:
        """Test that patterns are included when available."""
        service = InsightsService(async_session)
        insights = await service.get_insights(user_with_patterns)

        assert len(insights.patterns) >= 2
        pattern_names = [p.name for p in insights.patterns]
        assert PatternName.SLEEP_HRV_CORRELATION.value in pattern_names

    @pytest.mark.asyncio
    async def test_observations_generated(
        self, async_session: AsyncSession, user_7_days: str
    ) -> None:
        """Test that observations are generated."""
        service = InsightsService(async_session)
        insights = await service.get_insights(user_7_days)

        assert len(insights.observations) > 0
        # Should have onboarding observation for new user
        categories = [o.category for o in insights.observations]
        assert ObservationCategory.ONBOARDING in categories

    @pytest.mark.asyncio
    async def test_unlock_progress_calculated(
        self, async_session: AsyncSession, user_7_days: str
    ) -> None:
        """Test that unlock progress is calculated."""
        service = InsightsService(async_session)
        insights = await service.get_insights(user_7_days)

        assert insights.unlock_progress is not None
        assert insights.unlock_progress.next_unlock is not None
        assert insights.unlock_progress.days_until_next is not None
        assert insights.unlock_progress.percent_to_next is not None


class TestObservationGenerator:
    """Tests for ObservationGenerator."""

    def test_onboarding_observation_new_user(self) -> None:
        """Test onboarding observation for new users."""
        generator = ObservationGenerator()
        from polar_flow_server.schemas.insights import CurrentMetrics

        observations = generator.generate_observations(
            current_metrics=CurrentMetrics(),
            baselines={},
            patterns=[],
            anomalies=[],
            data_age_days=3,
        )

        assert len(observations) >= 1
        onboarding = [o for o in observations if o.category == ObservationCategory.ONBOARDING]
        assert len(onboarding) == 1
        assert "Building" in onboarding[0].fact

    def test_hrv_below_baseline_observation(self) -> None:
        """Test observation when HRV is below baseline."""
        generator = ObservationGenerator()
        from polar_flow_server.schemas.insights import BaselineComparison, CurrentMetrics

        baselines = {
            "hrv_rmssd": BaselineComparison(
                current=40.0,
                baseline=50.0,
                percent_of_baseline=80.0,
                status="ready",
            )
        }

        observations = generator.generate_observations(
            current_metrics=CurrentMetrics(hrv=40.0),
            baselines=baselines,
            patterns=[],
            anomalies=[],
            data_age_days=30,
        )

        hrv_obs = [o for o in observations if o.category == ObservationCategory.RECOVERY]
        assert len(hrv_obs) >= 1
        assert "below" in hrv_obs[0].fact.lower()
        assert hrv_obs[0].priority == ObservationPriority.HIGH

    def test_positive_observation_when_hrv_high(self) -> None:
        """Test positive observation when HRV is above baseline."""
        generator = ObservationGenerator()
        from polar_flow_server.schemas.insights import BaselineComparison, CurrentMetrics

        baselines = {
            "hrv_rmssd": BaselineComparison(
                current=60.0,
                baseline=50.0,
                percent_of_baseline=120.0,
                status="ready",
            )
        }

        observations = generator.generate_observations(
            current_metrics=CurrentMetrics(hrv=60.0),
            baselines=baselines,
            patterns=[],
            anomalies=[],
            data_age_days=30,
        )

        positive_obs = [o for o in observations if o.priority == ObservationPriority.POSITIVE]
        assert len(positive_obs) >= 1
        assert "above" in positive_obs[0].fact.lower()


class TestSuggestionGenerator:
    """Tests for suggestion generation."""

    def test_rest_day_suggestion_high_risk(self) -> None:
        """Test rest day suggestion for high overtraining risk."""
        generator = ObservationGenerator()
        from polar_flow_server.schemas.insights import Pattern

        patterns = [
            Pattern(
                name="overtraining_risk",
                pattern_type="composite",
                score=65.0,
                significance="high",
                factors=["HRV declining"],
            )
        ]

        suggestions = generator.generate_suggestions(
            baselines={},
            patterns=patterns,
            anomalies=[],
        )

        rest_suggestions = [s for s in suggestions if s.action == "rest_day"]
        assert len(rest_suggestions) == 1
        assert rest_suggestions[0].confidence > 0.5

    def test_no_suggestion_when_healthy(self) -> None:
        """Test that positive suggestion is given when healthy."""
        generator = ObservationGenerator()
        from polar_flow_server.schemas.insights import BaselineComparison

        baselines = {
            "hrv_rmssd": BaselineComparison(
                current=55.0,
                baseline=50.0,
                percent_of_baseline=110.0,
                status="ready",
            )
        }

        suggestions = generator.generate_suggestions(
            baselines=baselines,
            patterns=[],
            anomalies=[],
        )

        # Should have train_normally suggestion
        train_suggestions = [s for s in suggestions if s.action == "train_normally"]
        assert len(train_suggestions) == 1


class TestFeatureUnlockThresholds:
    """Tests for feature unlock thresholds."""

    def test_unlock_thresholds_values(self) -> None:
        """Test that unlock thresholds are set correctly."""
        assert UNLOCK_THRESHOLDS["baselines_7d"] == 7
        assert UNLOCK_THRESHOLDS["baselines_30d"] == 30
        assert UNLOCK_THRESHOLDS["patterns"] == 21
        assert UNLOCK_THRESHOLDS["anomaly_detection"] == 21
        assert UNLOCK_THRESHOLDS["ml_predictions"] == 60

    def test_feature_availability_at_zero_days(self) -> None:
        """Test no features available at 0 days."""
        service = InsightsService.__new__(InsightsService)
        availability = service._get_feature_availability(0)

        assert not availability.baselines_7d.available
        assert not availability.baselines_30d.available
        assert not availability.patterns.available
        assert not availability.anomaly_detection.available
        assert not availability.ml_predictions.available

    def test_feature_availability_at_60_days(self) -> None:
        """Test all features except ML available at 60 days."""
        service = InsightsService.__new__(InsightsService)
        availability = service._get_feature_availability(60)

        assert availability.baselines_7d.available
        assert availability.baselines_30d.available
        assert availability.patterns.available
        assert availability.anomaly_detection.available
        assert availability.ml_predictions.available
