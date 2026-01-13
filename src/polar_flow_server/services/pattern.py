"""Pattern detection service for correlations and composite scores."""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import mean

import structlog
from scipy import stats
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.models.baseline import UserBaseline
from polar_flow_server.models.cardio_load import CardioLoad
from polar_flow_server.models.pattern import (
    PatternAnalysis,
    PatternName,
    PatternType,
    Significance,
)
from polar_flow_server.models.recharge import NightlyRecharge
from polar_flow_server.models.sleep import Sleep

logger = structlog.get_logger()

# Minimum samples for statistical significance
MIN_SAMPLES_CORRELATION = 21  # Need n >= 20 for reliable Spearman correlation
MIN_SAMPLES_TREND = 7  # Minimum for trend analysis


@dataclass
class PatternResult:
    """Result of a pattern detection analysis."""

    pattern_type: str
    pattern_name: str
    score: float | None = None
    confidence: float | None = None
    significance: str = Significance.INSUFFICIENT.value
    details: dict[str, object] | None = None
    sample_count: int = 0
    metrics_involved: list[str] | None = None


class PatternService:
    """Service for detecting patterns and correlations in user health data.

    Detects:
    - Statistical correlations (Sleep-HRV, Activity-Sleep)
    - Composite risk scores (Overtraining risk)
    - Trends (HRV trend, Sleep trend)
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize pattern service.

        Args:
            session: Database session
        """
        self.session = session
        self.logger = logger.bind(service="pattern")

    async def detect_all_patterns(self, user_id: str) -> dict[str, str]:
        """Detect all patterns for a user.

        Args:
            user_id: User identifier

        Returns:
            Dict mapping pattern names to their significance

        Raises:
            Exception: Re-raises after rollback if pattern detection fails
        """
        self.logger.info("Detecting all patterns", user_id=user_id)

        results = {}

        try:
            # Correlations
            sleep_hrv = await self.detect_sleep_hrv_correlation(user_id)
            results[sleep_hrv.pattern_name] = sleep_hrv.significance
            await self._upsert_pattern(user_id, sleep_hrv)

            # Composite scores
            overtraining = await self.detect_overtraining_risk(user_id)
            results[overtraining.pattern_name] = overtraining.significance
            await self._upsert_pattern(user_id, overtraining)

            # Trends
            hrv_trend = await self.detect_hrv_trend(user_id)
            results[hrv_trend.pattern_name] = hrv_trend.significance
            await self._upsert_pattern(user_id, hrv_trend)

            sleep_trend = await self.detect_sleep_trend(user_id)
            results[sleep_trend.pattern_name] = sleep_trend.significance
            await self._upsert_pattern(user_id, sleep_trend)

            await self.session.commit()
        except Exception as e:
            await self.session.rollback()
            self.logger.error("Pattern detection failed", user_id=user_id, error=str(e))
            raise

        self.logger.info("Pattern detection complete", user_id=user_id, results=results)
        return results

    async def detect_sleep_hrv_correlation(self, user_id: str) -> PatternResult:
        """Analyze correlation between sleep quality and HRV.

        Uses Spearman correlation which is robust for non-normal distributions
        common in health metrics.

        Args:
            user_id: User identifier

        Returns:
            PatternResult with correlation coefficient and significance
        """
        self.logger.debug("Detecting sleep-HRV correlation", user_id=user_id)

        since_date = datetime.now(UTC).date() - timedelta(days=90)

        # Fetch sleep scores
        sleep_stmt = (
            select(Sleep.date, Sleep.sleep_score)
            .where(Sleep.user_id == user_id)
            .where(Sleep.date >= since_date)
            .where(Sleep.sleep_score.isnot(None))
            .order_by(Sleep.date)
        )
        sleep_result = await self.session.execute(sleep_stmt)
        sleep_data = {row.date: float(row.sleep_score) for row in sleep_result.fetchall()}

        # Fetch HRV values
        hrv_stmt = (
            select(NightlyRecharge.date, NightlyRecharge.hrv_avg)
            .where(NightlyRecharge.user_id == user_id)
            .where(NightlyRecharge.date >= since_date)
            .where(NightlyRecharge.hrv_avg.isnot(None))
            .order_by(NightlyRecharge.date)
        )
        hrv_result = await self.session.execute(hrv_stmt)
        hrv_data = {row.date: float(row.hrv_avg) for row in hrv_result.fetchall()}

        # Align by date (only use days where both metrics exist)
        common_dates = set(sleep_data.keys()) & set(hrv_data.keys())
        if len(common_dates) < MIN_SAMPLES_CORRELATION:
            return PatternResult(
                pattern_type=PatternType.CORRELATION.value,
                pattern_name=PatternName.SLEEP_HRV_CORRELATION.value,
                significance=Significance.INSUFFICIENT.value,
                sample_count=len(common_dates),
                metrics_involved=["sleep_score", "hrv_rmssd"],
                details={
                    "reason": f"Insufficient data: {len(common_dates)} samples, need {MIN_SAMPLES_CORRELATION}"
                },
            )

        # Extract aligned values
        sorted_dates = sorted(common_dates)
        sleep_values = [sleep_data[d] for d in sorted_dates]
        hrv_values = [hrv_data[d] for d in sorted_dates]

        # Calculate Spearman correlation (robust for non-normal distributions)
        result = stats.spearmanr(sleep_values, hrv_values)
        correlation = float(result.statistic)
        p_value = float(result.pvalue)

        # Handle NaN results (can occur with constant arrays or insufficient variance)
        if math.isnan(correlation) or math.isnan(p_value):
            self.logger.warning(
                "Spearman correlation returned NaN",
                user_id=user_id,
                sample_count=len(common_dates),
            )
            return PatternResult(
                pattern_type=PatternType.CORRELATION.value,
                pattern_name=PatternName.SLEEP_HRV_CORRELATION.value,
                significance=Significance.INSUFFICIENT.value,
                sample_count=len(common_dates),
                metrics_involved=["sleep_score", "hrv_rmssd"],
                details={"reason": "Could not compute correlation - data may lack variance"},
            )

        # Determine significance
        if p_value < 0.01:
            significance = Significance.HIGH.value
        elif p_value < 0.05:
            significance = Significance.MEDIUM.value
        else:
            significance = Significance.LOW.value

        # Interpret correlation strength
        abs_corr = abs(correlation)
        if abs_corr >= 0.7:
            strength = "strong"
        elif abs_corr >= 0.4:
            strength = "moderate"
        elif abs_corr >= 0.2:
            strength = "weak"
        else:
            strength = "negligible"

        direction = "positive" if correlation > 0 else "negative"
        interpretation = (
            f"{strength.capitalize()} {direction} correlation between sleep quality and HRV"
        )

        if correlation > 0.3 and p_value < 0.05:
            interpretation += ". Better sleep is associated with higher HRV."
        elif correlation < -0.3 and p_value < 0.05:
            interpretation += (
                ". This inverse relationship is unusual and may warrant investigation."
            )

        return PatternResult(
            pattern_type=PatternType.CORRELATION.value,
            pattern_name=PatternName.SLEEP_HRV_CORRELATION.value,
            score=float(correlation),
            confidence=float(1 - p_value),
            significance=significance,
            sample_count=len(common_dates),
            metrics_involved=["sleep_score", "hrv_rmssd"],
            details={
                "correlation_coefficient": float(correlation),
                "p_value": float(p_value),
                "strength": strength,
                "direction": direction,
                "interpretation": interpretation,
            },
        )

    async def detect_overtraining_risk(self, user_id: str) -> PatternResult:
        """Multi-metric analysis for overtraining detection.

        Scores 4 factors (0-25 points each):
        - HRV declining
        - Sleep quality declining
        - Resting HR elevated
        - Training load ratio high

        Args:
            user_id: User identifier

        Returns:
            PatternResult with risk score 0-100
        """
        self.logger.debug("Detecting overtraining risk", user_id=user_id)

        risk_score = 0
        factors: list[str] = []
        metrics_checked = 0

        # Get HRV trend (7-day vs 30-day baseline)
        hrv_trend = await self._get_metric_trend(user_id, "hrv")
        if hrv_trend is not None:
            metrics_checked += 1
            if hrv_trend < -10:  # HRV declining >10%
                risk_score += 25
                factors.append(f"HRV declining significantly ({hrv_trend:.1f}%)")
            elif hrv_trend < -5:
                risk_score += 15
                factors.append(f"HRV declining moderately ({hrv_trend:.1f}%)")

        # Get sleep trend
        sleep_trend = await self._get_metric_trend(user_id, "sleep")
        if sleep_trend is not None:
            metrics_checked += 1
            if sleep_trend < -10:
                risk_score += 25
                factors.append(f"Sleep quality declining ({sleep_trend:.1f}%)")
            elif sleep_trend < -5:
                risk_score += 15
                factors.append(f"Sleep quality declining slightly ({sleep_trend:.1f}%)")

        # Get resting HR trend (inverted - higher is worse)
        rhr_trend = await self._get_metric_trend(user_id, "resting_hr")
        if rhr_trend is not None:
            metrics_checked += 1
            if rhr_trend > 5:  # RHR increasing >5%
                risk_score += 25
                factors.append(f"Resting heart rate elevated ({rhr_trend:+.1f}%)")
            elif rhr_trend > 2:
                risk_score += 15
                factors.append(f"Resting heart rate slightly elevated ({rhr_trend:+.1f}%)")

        # Get training load ratio from cardio load
        load_ratio = await self._get_training_load_ratio(user_id)
        if load_ratio is not None:
            metrics_checked += 1
            if load_ratio > 1.5:
                risk_score += 25
                factors.append(f"Training load ratio high ({load_ratio:.2f})")
            elif load_ratio > 1.3:
                risk_score += 15
                factors.append(f"Training load ratio elevated ({load_ratio:.2f})")

        # Determine significance
        if metrics_checked < 2:
            significance = Significance.INSUFFICIENT.value
        elif risk_score >= 50:
            significance = Significance.HIGH.value
        elif risk_score >= 25:
            significance = Significance.MEDIUM.value
        else:
            significance = Significance.LOW.value

        # Generate recommendations
        recommendations = self._get_recovery_recommendations(risk_score, factors)

        return PatternResult(
            pattern_type=PatternType.COMPOSITE.value,
            pattern_name=PatternName.OVERTRAINING_RISK.value,
            score=float(risk_score),
            confidence=float(metrics_checked / 4) if metrics_checked > 0 else 0.0,
            significance=significance,
            sample_count=metrics_checked,
            metrics_involved=["hrv_rmssd", "sleep_score", "resting_hr", "training_load_ratio"],
            details={
                "risk_score": risk_score,
                "risk_factors": factors,
                "metrics_checked": metrics_checked,
                "recommendations": recommendations,
            },
        )

    async def detect_hrv_trend(self, user_id: str) -> PatternResult:
        """Detect 7-day HRV trend compared to 30-day baseline.

        Args:
            user_id: User identifier

        Returns:
            PatternResult with trend percentage
        """
        return await self._detect_metric_trend(
            user_id,
            metric_name="hrv",
            pattern_name=PatternName.HRV_TREND.value,
        )

    async def detect_sleep_trend(self, user_id: str) -> PatternResult:
        """Detect 7-day sleep score trend compared to 30-day baseline.

        Args:
            user_id: User identifier

        Returns:
            PatternResult with trend percentage
        """
        return await self._detect_metric_trend(
            user_id,
            metric_name="sleep",
            pattern_name=PatternName.SLEEP_TREND.value,
        )

    async def _detect_metric_trend(
        self, user_id: str, metric_name: str, pattern_name: str
    ) -> PatternResult:
        """Generic trend detection for any metric.

        Compares 7-day average to 30-day baseline.

        Args:
            user_id: User identifier
            metric_name: Which metric to analyze
            pattern_name: Pattern name for result

        Returns:
            PatternResult with trend percentage
        """
        trend = await self._get_metric_trend(user_id, metric_name)

        if trend is None:
            return PatternResult(
                pattern_type=PatternType.TREND.value,
                pattern_name=pattern_name,
                significance=Significance.INSUFFICIENT.value,
                metrics_involved=[metric_name],
                details={"reason": "Insufficient data for trend analysis"},
            )

        # Determine significance based on trend magnitude
        abs_trend = abs(trend)
        if abs_trend >= 10:
            significance = Significance.HIGH.value
        elif abs_trend >= 5:
            significance = Significance.MEDIUM.value
        else:
            significance = Significance.LOW.value

        direction = "improving" if trend > 0 else "declining" if trend < 0 else "stable"
        interpretation = f"{metric_name.upper()} is {direction} ({trend:+.1f}% from baseline)"

        return PatternResult(
            pattern_type=PatternType.TREND.value,
            pattern_name=pattern_name,
            score=float(trend),
            confidence=0.8,  # Trend confidence is high with sufficient data
            significance=significance,
            sample_count=7,  # 7-day trend
            metrics_involved=[metric_name],
            details={
                "trend_percent": float(trend),
                "direction": direction,
                "interpretation": interpretation,
            },
        )

    async def _get_metric_trend(self, user_id: str, metric: str) -> float | None:
        """Calculate trend for a metric (7-day avg vs 30-day baseline).

        Args:
            user_id: User identifier
            metric: Metric name (hrv, sleep, resting_hr)

        Returns:
            Percentage change or None if insufficient data
        """
        today = datetime.now(UTC).date()

        if metric == "hrv":
            stmt = (
                select(NightlyRecharge.date, NightlyRecharge.hrv_avg)
                .where(NightlyRecharge.user_id == user_id)
                .where(NightlyRecharge.date >= today - timedelta(days=30))
                .where(NightlyRecharge.hrv_avg.isnot(None))
            )
            result = await self.session.execute(stmt)
            data = [(row.date, float(row.hrv_avg)) for row in result.fetchall()]

        elif metric == "sleep":
            sleep_stmt = (
                select(Sleep.date, Sleep.sleep_score)
                .where(Sleep.user_id == user_id)
                .where(Sleep.date >= today - timedelta(days=30))
                .where(Sleep.sleep_score.isnot(None))
            )
            sleep_result = await self.session.execute(sleep_stmt)
            data = [(row.date, float(row.sleep_score)) for row in sleep_result.fetchall()]

        elif metric == "resting_hr":
            stmt = (
                select(NightlyRecharge.date, NightlyRecharge.heart_rate_avg)
                .where(NightlyRecharge.user_id == user_id)
                .where(NightlyRecharge.date >= today - timedelta(days=30))
                .where(NightlyRecharge.heart_rate_avg.isnot(None))
            )
            result = await self.session.execute(stmt)
            data = [(row.date, float(row.heart_rate_avg)) for row in result.fetchall()]

        else:
            return None

        if len(data) < MIN_SAMPLES_TREND:
            return None

        # Split into recent (7d) and baseline (older than 7d)
        recent_cutoff = today - timedelta(days=7)
        recent = [v for d, v in data if d >= recent_cutoff]
        baseline = [v for d, v in data if d < recent_cutoff]  # Exclude recent days

        if len(recent) < 3 or len(baseline) < MIN_SAMPLES_TREND:
            return None

        recent_avg = mean(recent)
        baseline_avg = mean(baseline)

        if baseline_avg == 0:
            return None

        return ((recent_avg - baseline_avg) / baseline_avg) * 100

    async def _get_training_load_ratio(self, user_id: str) -> float | None:
        """Get latest training load ratio from cardio load data.

        Args:
            user_id: User identifier

        Returns:
            Load ratio or None if not available
        """
        stmt = (
            select(CardioLoad.cardio_load_ratio)
            .where(CardioLoad.user_id == user_id)
            .where(CardioLoad.cardio_load_ratio.isnot(None))
            .where(CardioLoad.cardio_load_ratio > 0)
            .order_by(CardioLoad.date.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        return float(row) if row else None

    def _get_recovery_recommendations(self, risk_score: int, factors: list[str]) -> list[str]:
        """Generate recovery recommendations based on risk score.

        Args:
            risk_score: Overtraining risk score (0-100)
            factors: List of contributing risk factors

        Returns:
            List of recommendation strings
        """
        recommendations = []

        if risk_score >= 75:
            recommendations.append(
                "Consider taking a rest day or reducing training intensity significantly"
            )
            recommendations.append("Prioritize sleep quality and duration")
            recommendations.append(
                "Monitor symptoms of overtraining (fatigue, mood changes, decreased performance)"
            )
        elif risk_score >= 50:
            recommendations.append("Reduce training intensity for the next few days")
            recommendations.append("Focus on recovery activities (light stretching, walking)")
            recommendations.append("Ensure adequate sleep (7-9 hours)")
        elif risk_score >= 25:
            recommendations.append("Monitor your body's response to training")
            recommendations.append("Consider adding an extra recovery day this week")
        else:
            recommendations.append("Training load appears manageable")
            recommendations.append("Continue current training while monitoring recovery metrics")

        return recommendations

    async def _upsert_pattern(self, user_id: str, result: PatternResult) -> None:
        """Insert or update a pattern analysis result.

        Args:
            user_id: User identifier
            result: Pattern detection result
        """
        pattern_data = {
            "pattern_type": result.pattern_type,
            "pattern_name": result.pattern_name,
            "metrics_involved": result.metrics_involved or [],
            "analysis_window_days": 30,
            "score": result.score,
            "confidence": result.confidence,
            "significance": result.significance,
            "details": result.details,
            "sample_count": result.sample_count,
            "analyzed_at": datetime.now(UTC),
        }

        stmt = insert(PatternAnalysis).values(user_id=user_id, **pattern_data)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_user_pattern",
            set_=pattern_data,
        )

        await self.session.execute(stmt)

    async def get_user_patterns(self, user_id: str) -> list[PatternAnalysis]:
        """Get all patterns for a user.

        Args:
            user_id: User identifier

        Returns:
            List of PatternAnalysis records
        """
        stmt = select(PatternAnalysis).where(PatternAnalysis.user_id == user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_pattern(
        self,
        user_id: str,
        pattern_name: str,
    ) -> PatternAnalysis | None:
        """Get a specific pattern for a user.

        Args:
            user_id: User identifier
            pattern_name: Pattern to retrieve

        Returns:
            PatternAnalysis record or None
        """
        stmt = (
            select(PatternAnalysis)
            .where(PatternAnalysis.user_id == user_id)
            .where(PatternAnalysis.pattern_name == pattern_name)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class AnomalyService:
    """Service for detecting anomalies across all metrics.

    Uses IQR-based detection which is robust to non-normal distributions.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize anomaly service.

        Args:
            session: Database session
        """
        self.session = session
        self.logger = logger.bind(service="anomaly")

    async def detect_all_anomalies(self, user_id: str) -> list[dict[str, object]]:
        """Detect anomalies across all metrics using stored baselines.

        Args:
            user_id: User identifier

        Returns:
            List of detected anomalies
        """
        self.logger.debug("Detecting all anomalies", user_id=user_id)

        anomalies = []

        # Get all baselines for user
        stmt = select(UserBaseline).where(UserBaseline.user_id == user_id)
        result = await self.session.execute(stmt)
        baselines = list(result.scalars().all())

        if not baselines:
            return []

        # Get latest values for each metric
        latest_values = await self._get_latest_metric_values(user_id)

        for baseline in baselines:
            metric_name = baseline.metric_name
            current_value = latest_values.get(metric_name)

            if current_value is None:
                continue

            is_anomaly, severity = baseline.is_anomaly(current_value)

            if is_anomaly:
                direction = "above" if current_value > (baseline.baseline_value or 0) else "below"
                anomalies.append(
                    {
                        "metric_name": metric_name,
                        "current_value": current_value,
                        "baseline_value": baseline.baseline_value,
                        "median_value": baseline.median_value,
                        "lower_bound": baseline.lower_bound,
                        "upper_bound": baseline.upper_bound,
                        "direction": direction,
                        "severity": severity,
                        "deviation_percent": self._calc_deviation(
                            current_value, baseline.baseline_value
                        ),
                    }
                )

        self.logger.debug(
            "Anomaly detection complete",
            user_id=user_id,
            anomaly_count=len(anomalies),
        )

        return anomalies

    async def _get_latest_metric_values(self, user_id: str) -> dict[str, float]:
        """Get the most recent value for each metric.

        Args:
            user_id: User identifier

        Returns:
            Dict mapping metric names to latest values
        """
        values: dict[str, float] = {}

        # HRV from nightly recharge
        stmt = (
            select(NightlyRecharge.hrv_avg)
            .where(NightlyRecharge.user_id == user_id)
            .where(NightlyRecharge.hrv_avg.isnot(None))
            .order_by(NightlyRecharge.date.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        hrv = result.scalar_one_or_none()
        if hrv:
            values["hrv_rmssd"] = float(hrv)

        # Sleep score
        sleep_stmt = (
            select(Sleep.sleep_score)
            .where(Sleep.user_id == user_id)
            .where(Sleep.sleep_score.isnot(None))
            .order_by(Sleep.date.desc())
            .limit(1)
        )
        sleep_result = await self.session.execute(sleep_stmt)
        sleep = sleep_result.scalar_one_or_none()
        if sleep:
            values["sleep_score"] = float(sleep)

        # Resting HR
        stmt = (
            select(NightlyRecharge.heart_rate_avg)
            .where(NightlyRecharge.user_id == user_id)
            .where(NightlyRecharge.heart_rate_avg.isnot(None))
            .order_by(NightlyRecharge.date.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        rhr = result.scalar_one_or_none()
        if rhr:
            values["resting_hr"] = float(rhr)

        # Training load
        stmt = (
            select(CardioLoad.cardio_load)
            .where(CardioLoad.user_id == user_id)
            .where(CardioLoad.cardio_load.isnot(None))
            .where(CardioLoad.cardio_load > 0)
            .order_by(CardioLoad.date.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        load = result.scalar_one_or_none()
        if load:
            values["training_load"] = float(load)

        # Training load ratio
        stmt = (
            select(CardioLoad.cardio_load_ratio)
            .where(CardioLoad.user_id == user_id)
            .where(CardioLoad.cardio_load_ratio.isnot(None))
            .where(CardioLoad.cardio_load_ratio > 0)
            .order_by(CardioLoad.date.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        ratio = result.scalar_one_or_none()
        if ratio:
            values["training_load_ratio"] = float(ratio)

        return values

    def _calc_deviation(self, current: float, baseline: float | None) -> float | None:
        """Calculate percentage deviation from baseline.

        Args:
            current: Current value
            baseline: Baseline value

        Returns:
            Percentage deviation or None
        """
        if baseline is None or baseline == 0:
            return None
        return ((current - baseline) / baseline) * 100
