"""Observation generator for natural language insights."""

import structlog

from polar_flow_server.schemas.insights import (
    Anomaly,
    BaselineComparison,
    CurrentMetrics,
    Observation,
    ObservationCategory,
    ObservationPriority,
    Pattern,
    Suggestion,
    TrendDirection,
)

logger = structlog.get_logger()


class ObservationGenerator:
    """Generate natural language observations from analytics data.

    Converts numerical metrics, patterns, and anomalies into
    human-readable observations that coaching layers can use
    to communicate with users.
    """

    def __init__(self) -> None:
        """Initialize observation generator."""
        self.logger = logger.bind(service="observations")

    def generate_observations(
        self,
        current_metrics: CurrentMetrics,
        baselines: dict[str, BaselineComparison],
        patterns: list[Pattern],
        anomalies: list[Anomaly],
        data_age_days: int,
    ) -> list[Observation]:
        """Generate all observations from analytics data.

        Args:
            current_metrics: Current metric values
            baselines: Baseline comparisons by metric
            patterns: Detected patterns
            anomalies: Detected anomalies
            data_age_days: Days of data available

        Returns:
            List of observations sorted by priority
        """
        observations: list[Observation] = []

        # Check for onboarding state
        if data_age_days < 7:
            observations.append(self._onboarding_observation(data_age_days))
        elif data_age_days < 21:
            observations.append(self._building_baselines_observation(data_age_days))

        # Anomaly observations (highest priority)
        for anomaly in anomalies:
            observations.append(self._anomaly_observation(anomaly))

        # Baseline observations
        if "hrv_rmssd" in baselines:
            obs = self._hrv_observation(baselines["hrv_rmssd"], current_metrics.hrv)
            if obs:
                observations.append(obs)

        if "sleep_score" in baselines:
            obs = self._sleep_observation(baselines["sleep_score"], current_metrics.sleep_score)
            if obs:
                observations.append(obs)

        # Pattern observations
        for pattern in patterns:
            obs = self._pattern_observation(pattern)
            if obs:
                observations.append(obs)

        # Sort by priority
        priority_order = {
            ObservationPriority.CRITICAL: 0,
            ObservationPriority.HIGH: 1,
            ObservationPriority.MEDIUM: 2,
            ObservationPriority.LOW: 3,
            ObservationPriority.INFO: 4,
            ObservationPriority.POSITIVE: 5,
        }

        return sorted(observations, key=lambda o: priority_order.get(o.priority, 99))

    def generate_suggestions(
        self,
        baselines: dict[str, BaselineComparison],
        patterns: list[Pattern],
        anomalies: list[Anomaly],
    ) -> list[Suggestion]:
        """Generate actionable suggestions based on insights.

        Args:
            baselines: Baseline comparisons
            patterns: Detected patterns
            anomalies: Detected anomalies

        Returns:
            List of suggestions
        """
        suggestions: list[Suggestion] = []

        # Check for overtraining risk
        overtraining = next(
            (p for p in patterns if p.name == "overtraining_risk" and p.score), None
        )
        if overtraining and overtraining.score and overtraining.score >= 50:
            suggestions.append(
                Suggestion(
                    action="rest_day",
                    description="Take a rest day or do light recovery activity",
                    confidence=min(overtraining.score / 100, 0.95),
                    reason="Elevated overtraining risk score indicates need for recovery",
                )
            )
        elif overtraining and overtraining.score and overtraining.score >= 25:
            suggestions.append(
                Suggestion(
                    action="reduce_intensity",
                    description="Consider reducing training intensity",
                    confidence=min(overtraining.score / 100, 0.8),
                    reason="Moderate overtraining risk detected",
                )
            )

        # Check HRV baseline
        hrv = baselines.get("hrv_rmssd")
        if hrv and hrv.percent_of_baseline and hrv.percent_of_baseline < 85:
            suggestions.append(
                Suggestion(
                    action="prioritize_recovery",
                    description="Prioritize sleep and recovery today",
                    confidence=0.85,
                    reason=f"HRV is {100 - hrv.percent_of_baseline:.0f}% below baseline",
                )
            )

        # Check for critical anomalies
        critical_anomalies = [a for a in anomalies if a.severity == "critical"]
        if critical_anomalies:
            suggestions.append(
                Suggestion(
                    action="monitor_closely",
                    description="Monitor your metrics closely today",
                    confidence=0.9,
                    reason=f"Critical anomaly detected in {critical_anomalies[0].metric}",
                )
            )

        # Positive suggestions when everything is good
        if not suggestions:
            if hrv and hrv.percent_of_baseline and hrv.percent_of_baseline >= 100:
                suggestions.append(
                    Suggestion(
                        action="train_normally",
                        description="Body is well-recovered, train as planned",
                        confidence=0.85,
                        reason="HRV at or above baseline indicates good recovery",
                    )
                )

        return suggestions

    def _onboarding_observation(self, data_age_days: int) -> Observation:
        """Create onboarding observation for new users."""
        return Observation(
            category=ObservationCategory.ONBOARDING,
            priority=ObservationPriority.INFO,
            fact=f"Building your personal baselines ({data_age_days}/7 days)",
            context=f"Keep wearing your device. Basic insights unlock in {7 - data_age_days} days.",
            trend=None,
        )

    def _building_baselines_observation(self, data_age_days: int) -> Observation:
        """Create observation for users still building baselines."""
        days_to_patterns = max(21 - data_age_days, 0)
        return Observation(
            category=ObservationCategory.ONBOARDING,
            priority=ObservationPriority.INFO,
            fact=f"Your baselines are being established ({data_age_days} days of data)",
            context=f"Pattern detection unlocks in {days_to_patterns} days. "
            "Accuracy improves over time.",
            trend=None,
        )

    def _anomaly_observation(self, anomaly: Anomaly) -> Observation:
        """Create observation from an anomaly."""
        metric_display = anomaly.metric.replace("_", " ").upper()

        if anomaly.severity == "critical":
            priority = ObservationPriority.CRITICAL
            fact = f"{metric_display} is significantly {anomaly.direction} normal range"
        else:
            priority = ObservationPriority.HIGH
            fact = f"{metric_display} is {anomaly.direction} normal range"

        return Observation(
            category=ObservationCategory.ANOMALY,
            priority=priority,
            fact=fact,
            context=f"Current: {anomaly.current_value:.1f}, "
            f"Baseline: {anomaly.baseline_value:.1f} "
            f"({anomaly.deviation_percent:+.0f}%)",
            trend=TrendDirection.ANOMALOUS,
        )

    def _hrv_observation(
        self, baseline: BaselineComparison, current_hrv: float | None
    ) -> Observation | None:
        """Create HRV observation from baseline comparison."""
        if not baseline.percent_of_baseline or baseline.status == "insufficient":
            return None

        pct = baseline.percent_of_baseline

        if pct < 85:
            return Observation(
                category=ObservationCategory.RECOVERY,
                priority=ObservationPriority.HIGH,
                fact=f"HRV is {100 - pct:.0f}% below personal baseline",
                context=f"Current: {current_hrv:.0f}ms, Baseline: {baseline.baseline:.0f}ms"
                if current_hrv and baseline.baseline
                else None,
                trend=baseline.trend,
            )
        elif pct > 110:
            return Observation(
                category=ObservationCategory.RECOVERY,
                priority=ObservationPriority.POSITIVE,
                fact=f"HRV is {pct - 100:.0f}% above baseline - excellent recovery",
                context="Body is well-recovered and ready for training",
                trend=TrendDirection.IMPROVING,
            )

        return None

    def _sleep_observation(
        self, baseline: BaselineComparison, current_score: int | None
    ) -> Observation | None:
        """Create sleep observation from baseline comparison."""
        if not baseline.percent_of_baseline or baseline.status == "insufficient":
            return None

        # Check for declining trend
        if baseline.trend == TrendDirection.DECLINING and (baseline.trend_days or 0) >= 3:
            return Observation(
                category=ObservationCategory.SLEEP,
                priority=ObservationPriority.MEDIUM,
                fact=f"Sleep quality has been declining for {baseline.trend_days} days",
                context=f"Current score: {current_score}" if current_score else None,
                trend=TrendDirection.DECLINING,
            )

        pct = baseline.percent_of_baseline
        if pct < 85:
            return Observation(
                category=ObservationCategory.SLEEP,
                priority=ObservationPriority.MEDIUM,
                fact=f"Sleep score is {100 - pct:.0f}% below your average",
                context=f"Current: {current_score}, Baseline: {baseline.baseline:.0f}"
                if current_score and baseline.baseline
                else None,
                trend=baseline.trend,
            )

        return None

    def _pattern_observation(self, pattern: Pattern) -> Observation | None:
        """Create observation from a detected pattern."""
        if pattern.significance == "insufficient":
            return None

        if pattern.name == "overtraining_risk" and pattern.score:
            if pattern.score >= 50:
                return Observation(
                    category=ObservationCategory.TRAINING,
                    priority=ObservationPriority.HIGH,
                    fact=f"Overtraining risk is elevated ({pattern.score:.0f}/100)",
                    context=", ".join(pattern.factors) if pattern.factors else None,
                    trend=TrendDirection.DECLINING,
                )
            elif pattern.score >= 25:
                return Observation(
                    category=ObservationCategory.TRAINING,
                    priority=ObservationPriority.MEDIUM,
                    fact=f"Moderate overtraining indicators detected ({pattern.score:.0f}/100)",
                    context=", ".join(pattern.factors) if pattern.factors else None,
                    trend=TrendDirection.STABLE,
                )

        if pattern.name == "sleep_hrv_correlation" and pattern.significance == "high":
            if pattern.score and pattern.score > 0.5:
                return Observation(
                    category=ObservationCategory.RECOVERY,
                    priority=ObservationPriority.INFO,
                    fact="Strong connection between your sleep quality and HRV detected",
                    context="Better sleep directly improves your recovery metrics",
                    trend=None,
                )

        return None
