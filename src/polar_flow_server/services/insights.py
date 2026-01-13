"""Insights aggregation service."""

from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.models.baseline import UserBaseline
from polar_flow_server.models.cardio_load import CardioLoad
from polar_flow_server.models.pattern import PatternAnalysis
from polar_flow_server.models.recharge import NightlyRecharge
from polar_flow_server.models.sleep import Sleep
from polar_flow_server.schemas.insights import (
    Anomaly,
    BaselineComparison,
    CurrentMetrics,
    FeatureAvailability,
    FeatureStatus,
    InsightStatus,
    Pattern,
    TrendDirection,
    UnlockProgress,
    UserInsights,
)
from polar_flow_server.services.observations import ObservationGenerator
from polar_flow_server.services.pattern import AnomalyService

logger = structlog.get_logger()

# Feature unlock thresholds (days of data required)
UNLOCK_THRESHOLDS = {
    "baselines_7d": 7,
    "baselines_30d": 30,
    "patterns": 21,
    "anomaly_detection": 21,
    "ml_predictions": 60,
}


class InsightsService:
    """Service for aggregating all analytics into unified insights.

    Combines baselines, patterns, anomalies, and observations into
    a single comprehensive response for downstream consumers.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize insights service.

        Args:
            session: Database session
        """
        self.session = session
        self.logger = logger.bind(service="insights")
        self.observation_generator = ObservationGenerator()

    async def get_insights(self, user_id: str) -> UserInsights:
        """Get complete insights for a user.

        Args:
            user_id: User identifier

        Returns:
            Complete UserInsights response
        """
        self.logger.info("Generating insights", user_id=user_id)

        # Calculate data age
        data_age_days = await self._get_data_age_days(user_id)
        data_freshness = await self._get_data_freshness(user_id)

        # Determine overall status and feature availability
        status = self._determine_status(data_age_days)
        feature_availability = self._get_feature_availability(data_age_days)
        unlock_progress = self._get_unlock_progress(data_age_days)

        # Get current metrics
        current_metrics = await self._get_current_metrics(user_id)

        # Get baselines
        baselines = await self._get_baselines(user_id)

        # Get patterns (if available)
        patterns: list[Pattern] = []
        if data_age_days >= UNLOCK_THRESHOLDS["patterns"]:
            patterns = await self._get_patterns(user_id)

        # Get anomalies (if available)
        anomalies: list[Anomaly] = []
        if data_age_days >= UNLOCK_THRESHOLDS["anomaly_detection"]:
            anomalies = await self._get_anomalies(user_id)

        # Generate observations
        observations = self.observation_generator.generate_observations(
            current_metrics=current_metrics,
            baselines=baselines,
            patterns=patterns,
            anomalies=anomalies,
            data_age_days=data_age_days,
        )

        # Generate suggestions
        suggestions = self.observation_generator.generate_suggestions(
            baselines=baselines,
            patterns=patterns,
            anomalies=anomalies,
        )

        return UserInsights(
            user_id=user_id,
            generated_at=datetime.now(UTC),
            data_freshness=data_freshness,
            data_age_days=data_age_days,
            status=status,
            feature_availability=feature_availability,
            unlock_progress=unlock_progress,
            current_metrics=current_metrics,
            baselines=baselines,
            patterns=patterns,
            anomalies=anomalies,
            observations=observations,
            suggestions=suggestions,
        )

    async def _get_data_age_days(self, user_id: str) -> int:
        """Get the number of days of data available for a user."""
        # Check earliest date across key tables
        tables = [
            (Sleep, Sleep.date),
            (NightlyRecharge, NightlyRecharge.date),
        ]

        earliest_date = None

        for model, date_col in tables:
            stmt = (
                select(func.min(date_col)).where(model.user_id == user_id)  # type: ignore[attr-defined]
            )
            result = await self.session.execute(stmt)
            min_date = result.scalar()
            if min_date:
                if earliest_date is None or min_date < earliest_date:
                    earliest_date = min_date

        if earliest_date is None:
            return 0

        today = datetime.now(UTC).date()
        return (today - earliest_date).days + 1

    async def _get_data_freshness(self, user_id: str) -> datetime | None:
        """Get timestamp of most recent data."""
        # Check most recent date across key tables
        tables = [
            (Sleep, Sleep.date),
            (NightlyRecharge, NightlyRecharge.date),
        ]

        latest_date = None

        for model, date_col in tables:
            stmt = (
                select(func.max(date_col)).where(model.user_id == user_id)  # type: ignore[attr-defined]
            )
            result = await self.session.execute(stmt)
            max_date = result.scalar()
            if max_date:
                if latest_date is None or max_date > latest_date:
                    latest_date = max_date

        if latest_date:
            return datetime.combine(latest_date, datetime.min.time(), tzinfo=UTC)
        return None

    def _determine_status(self, data_age_days: int) -> InsightStatus:
        """Determine overall insights status based on data availability."""
        if data_age_days < 7:
            return InsightStatus.UNAVAILABLE
        elif data_age_days < 21:
            return InsightStatus.PARTIAL
        else:
            return InsightStatus.READY

    def _get_feature_availability(self, data_age_days: int) -> FeatureAvailability:
        """Get feature availability based on data age."""
        return FeatureAvailability(
            baselines_7d=self._feature_status("baselines_7d", data_age_days),
            baselines_30d=self._feature_status("baselines_30d", data_age_days),
            patterns=self._feature_status("patterns", data_age_days),
            anomaly_detection=self._feature_status("anomaly_detection", data_age_days),
            ml_predictions=self._feature_status("ml_predictions", data_age_days),
        )

    def _feature_status(self, feature: str, data_age_days: int) -> FeatureStatus:
        """Get status for a specific feature."""
        threshold = UNLOCK_THRESHOLDS.get(feature, 999)
        available = data_age_days >= threshold

        if available:
            return FeatureStatus(available=True, message=None, unlock_at_days=threshold)
        else:
            days_remaining = threshold - data_age_days
            return FeatureStatus(
                available=False,
                message=f"Unlocks in {days_remaining} days",
                unlock_at_days=threshold,
            )

    def _get_unlock_progress(self, data_age_days: int) -> UnlockProgress | None:
        """Get progress towards next feature unlock."""
        # Find next feature to unlock
        next_feature = None
        days_until = None

        for feature, threshold in sorted(UNLOCK_THRESHOLDS.items(), key=lambda x: x[1]):
            if data_age_days < threshold:
                next_feature = feature
                days_until = threshold - data_age_days
                break

        if next_feature is None:
            return None

        threshold = UNLOCK_THRESHOLDS[next_feature]
        percent = (data_age_days / threshold) * 100

        return UnlockProgress(
            next_unlock=next_feature,
            days_until_next=days_until,
            percent_to_next=min(percent, 99.9),
        )

    async def _get_current_metrics(self, user_id: str) -> CurrentMetrics:
        """Get most recent values of key metrics."""
        # Get most recent HRV
        hrv_stmt = (
            select(NightlyRecharge.hrv_avg)
            .where(NightlyRecharge.user_id == user_id)
            .where(NightlyRecharge.hrv_avg.isnot(None))
            .order_by(NightlyRecharge.date.desc())
            .limit(1)
        )
        hrv_result = await self.session.execute(hrv_stmt)
        hrv = hrv_result.scalar()

        # Get most recent sleep score
        sleep_stmt = (
            select(Sleep.sleep_score)
            .where(Sleep.user_id == user_id)
            .where(Sleep.sleep_score.isnot(None))
            .order_by(Sleep.date.desc())
            .limit(1)
        )
        sleep_result = await self.session.execute(sleep_stmt)
        sleep_score = sleep_result.scalar()

        # Get most recent resting HR
        rhr_stmt = (
            select(NightlyRecharge.heart_rate_avg)
            .where(NightlyRecharge.user_id == user_id)
            .where(NightlyRecharge.heart_rate_avg.isnot(None))
            .order_by(NightlyRecharge.date.desc())
            .limit(1)
        )
        rhr_result = await self.session.execute(rhr_stmt)
        resting_hr = rhr_result.scalar()

        # Get most recent training load ratio
        ratio_stmt = (
            select(CardioLoad.cardio_load_ratio)
            .where(CardioLoad.user_id == user_id)
            .where(CardioLoad.cardio_load_ratio.isnot(None))
            .order_by(CardioLoad.date.desc())
            .limit(1)
        )
        ratio_result = await self.session.execute(ratio_stmt)
        load_ratio = ratio_result.scalar()

        return CurrentMetrics(
            hrv=hrv,
            sleep_score=sleep_score,
            resting_hr=resting_hr,
            training_load_ratio=load_ratio,
        )

    async def _get_baselines(self, user_id: str) -> dict[str, BaselineComparison]:
        """Get baseline comparisons for all metrics."""
        baselines: dict[str, BaselineComparison] = {}

        # Query all baselines
        stmt = select(UserBaseline).where(UserBaseline.user_id == user_id)
        result = await self.session.execute(stmt)
        baseline_records = result.scalars().all()

        for baseline in baseline_records:
            # Calculate percent of baseline
            current = await self._get_current_value(user_id, baseline.metric_name)
            percent = None
            if current is not None and baseline.baseline_value:
                percent = (current / baseline.baseline_value) * 100

            # Determine trend (simplified - could be enhanced)
            trend = self._calculate_trend(baseline)

            baselines[baseline.metric_name] = BaselineComparison(
                current=current,
                baseline=baseline.baseline_value,
                baseline_7d=baseline.baseline_7d,
                baseline_30d=baseline.baseline_30d,
                percent_of_baseline=percent,
                trend=trend,
                trend_days=None,  # Would require historical analysis
                status=baseline.status,
            )

        return baselines

    async def _get_current_value(self, user_id: str, metric_name: str) -> float | None:
        """Get current value for a specific metric."""
        if metric_name == "hrv_rmssd":
            stmt = (
                select(NightlyRecharge.hrv_avg)
                .where(NightlyRecharge.user_id == user_id)
                .order_by(NightlyRecharge.date.desc())
                .limit(1)
            )
        elif metric_name == "sleep_score":
            stmt = (
                select(Sleep.sleep_score)
                .where(Sleep.user_id == user_id)
                .order_by(Sleep.date.desc())
                .limit(1)
            )
        elif metric_name == "resting_hr":
            stmt = (
                select(NightlyRecharge.heart_rate_avg)
                .where(NightlyRecharge.user_id == user_id)
                .order_by(NightlyRecharge.date.desc())
                .limit(1)
            )
        elif metric_name == "training_load":
            stmt = (
                select(CardioLoad.cardio_load)
                .where(CardioLoad.user_id == user_id)
                .order_by(CardioLoad.date.desc())
                .limit(1)
            )
        elif metric_name == "training_load_ratio":
            stmt = (
                select(CardioLoad.cardio_load_ratio)
                .where(CardioLoad.user_id == user_id)
                .order_by(CardioLoad.date.desc())
                .limit(1)
            )
        else:
            return None

        result = await self.session.execute(stmt)
        return result.scalar()

    def _calculate_trend(self, baseline: UserBaseline) -> TrendDirection | None:
        """Calculate trend direction from baseline data."""
        if baseline.baseline_7d is None or baseline.baseline_30d is None:
            return None

        diff_percent = (
            (baseline.baseline_7d - baseline.baseline_30d) / baseline.baseline_30d
        ) * 100

        if diff_percent > 5:
            return TrendDirection.IMPROVING
        elif diff_percent < -5:
            return TrendDirection.DECLINING
        else:
            return TrendDirection.STABLE

    async def _get_patterns(self, user_id: str) -> list[Pattern]:
        """Get detected patterns for a user."""
        stmt = (
            select(PatternAnalysis)
            .where(PatternAnalysis.user_id == user_id)
            .order_by(PatternAnalysis.analyzed_at.desc())
        )
        result = await self.session.execute(stmt)
        pattern_records = result.scalars().all()

        patterns: list[Pattern] = []
        for p in pattern_records:
            # Extract factors from details
            factors: list[str] = []
            interpretation = None
            if p.details:
                if "risk_factors" in p.details:
                    factors = p.details["risk_factors"]
                if "interpretation" in p.details:
                    interpretation = str(p.details["interpretation"])

            patterns.append(
                Pattern(
                    name=p.pattern_name,
                    pattern_type=p.pattern_type,
                    score=p.score,
                    significance=p.significance,
                    factors=factors,
                    interpretation=interpretation,
                )
            )

        return patterns

    async def _get_anomalies(self, user_id: str) -> list[Anomaly]:
        """Get detected anomalies for a user."""
        anomaly_service = AnomalyService(self.session)
        anomaly_dicts = await anomaly_service.detect_all_anomalies(user_id)

        anomalies: list[Anomaly] = []
        for a in anomaly_dicts:
            anomalies.append(
                Anomaly(
                    metric=a["metric_name"],
                    current_value=a["current_value"],
                    baseline_value=a["baseline_value"],
                    deviation_percent=a["deviation_percent"],
                    direction=a["direction"],
                    severity=a["severity"],
                )
            )

        return anomalies
