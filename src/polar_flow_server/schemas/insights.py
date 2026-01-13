"""Pydantic schemas for the unified insights API response."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class InsightStatus(str, Enum):
    """Status of insights availability."""

    READY = "ready"  # Full insights available
    PARTIAL = "partial"  # Some features available
    UNAVAILABLE = "unavailable"  # Not enough data


class ObservationPriority(str, Enum):
    """Priority level for observations."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"
    POSITIVE = "positive"


class ObservationCategory(str, Enum):
    """Category of observation."""

    RECOVERY = "recovery"
    SLEEP = "sleep"
    TRAINING = "training"
    ANOMALY = "anomaly"
    ONBOARDING = "onboarding"
    TREND = "trend"


class TrendDirection(str, Enum):
    """Direction of a trend."""

    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"
    ANOMALOUS = "anomalous"


class FeatureStatus(BaseModel):
    """Status of a single feature."""

    available: bool = Field(description="Whether this feature is available")
    message: str | None = Field(
        default=None, description="Message about availability (e.g., 'Unlocks in 5 days')"
    )
    unlock_at_days: int | None = Field(default=None, description="Days of data required to unlock")


class FeatureAvailability(BaseModel):
    """Availability of analytics features based on data history."""

    baselines_7d: FeatureStatus = Field(description="7-day rolling baselines")
    baselines_30d: FeatureStatus = Field(description="30-day baselines")
    patterns: FeatureStatus = Field(description="Pattern detection (correlations, trends)")
    anomaly_detection: FeatureStatus = Field(description="Anomaly detection")
    ml_predictions: FeatureStatus = Field(description="ML-based predictions")


class UnlockProgress(BaseModel):
    """Progress towards unlocking the next feature."""

    next_unlock: str | None = Field(description="Name of next feature to unlock")
    days_until_next: int | None = Field(description="Days until next unlock")
    percent_to_next: float | None = Field(description="Progress percentage to next unlock")


class CurrentMetrics(BaseModel):
    """Current values of key health metrics."""

    hrv: float | None = Field(default=None, description="Most recent HRV (ms)")
    sleep_score: int | None = Field(default=None, description="Most recent sleep score")
    resting_hr: int | None = Field(default=None, description="Most recent resting heart rate")
    training_load_ratio: float | None = Field(
        default=None, description="Acute:chronic training load ratio"
    )


class BaselineComparison(BaseModel):
    """Comparison of current value to personal baseline."""

    current: float | None = Field(description="Current value")
    baseline: float | None = Field(description="Personal baseline value")
    baseline_7d: float | None = Field(default=None, description="7-day rolling average")
    baseline_30d: float | None = Field(default=None, description="30-day rolling average")
    percent_of_baseline: float | None = Field(
        default=None, description="Current as percentage of baseline"
    )
    trend: TrendDirection | None = Field(default=None, description="Recent trend direction")
    trend_days: int | None = Field(default=None, description="Days of current trend")
    status: str = Field(description="Baseline status (ready, partial, insufficient)")


class Pattern(BaseModel):
    """Detected pattern from analytics."""

    name: str = Field(description="Pattern identifier")
    pattern_type: str = Field(description="Type (correlation, trend, composite)")
    score: float | None = Field(default=None, description="Pattern score or coefficient")
    significance: str = Field(description="Statistical significance (high, medium, low)")
    factors: list[str] = Field(default_factory=list, description="Contributing factors")
    interpretation: str | None = Field(default=None, description="Human-readable interpretation")


class Anomaly(BaseModel):
    """Detected anomaly in metrics."""

    metric: str = Field(description="Metric name")
    current_value: float = Field(description="Current anomalous value")
    baseline_value: float = Field(description="Expected baseline value")
    deviation_percent: float = Field(description="Percent deviation from baseline")
    direction: str = Field(description="'above' or 'below' baseline")
    severity: str = Field(description="'warning' or 'critical'")


class Observation(BaseModel):
    """Natural language observation for coaching layer."""

    category: ObservationCategory = Field(description="Observation category")
    priority: ObservationPriority = Field(description="Priority level")
    fact: str = Field(description="The factual observation")
    context: str | None = Field(default=None, description="Additional context")
    trend: TrendDirection | None = Field(default=None, description="Associated trend")


class Suggestion(BaseModel):
    """Actionable suggestion based on insights."""

    action: str = Field(description="Suggested action identifier")
    description: str = Field(description="Human-readable description")
    confidence: float = Field(ge=0, le=1, description="Confidence in suggestion (0-1)")
    reason: str = Field(description="Why this is suggested")


class UserInsights(BaseModel):
    """Complete insights package for a user.

    This is the primary response from the /insights endpoint.
    It aggregates baselines, patterns, anomalies, and observations
    into a single, comprehensive response for downstream consumers.
    """

    # Metadata
    user_id: str = Field(description="User identifier")
    generated_at: datetime = Field(description="When insights were generated")
    data_freshness: datetime | None = Field(
        default=None, description="Timestamp of most recent data"
    )
    data_age_days: int = Field(description="Days of data available")

    # Status
    status: InsightStatus = Field(description="Overall insights availability")
    feature_availability: FeatureAvailability = Field(description="What features are available")
    unlock_progress: UnlockProgress | None = Field(
        default=None, description="Progress to next feature unlock"
    )

    # Current state
    current_metrics: CurrentMetrics = Field(description="Current metric values")

    # Baselines comparison
    baselines: dict[str, BaselineComparison] = Field(
        default_factory=dict, description="Baseline comparisons by metric"
    )

    # Patterns
    patterns: list[Pattern] = Field(default_factory=list, description="Detected patterns")

    # Anomalies
    anomalies: list[Anomaly] = Field(default_factory=list, description="Detected anomalies")

    # Natural language observations
    observations: list[Observation] = Field(
        default_factory=list, description="Observations for coaching"
    )

    # Suggestions
    suggestions: list[Suggestion] = Field(
        default_factory=list, description="Actionable suggestions"
    )

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "user_id": "12345678",
                "generated_at": "2026-01-13T10:30:00Z",
                "data_freshness": "2026-01-13T06:00:00Z",
                "data_age_days": 45,
                "status": "ready",
                "feature_availability": {
                    "baselines_7d": {"available": True, "message": None},
                    "baselines_30d": {"available": True, "message": None},
                    "patterns": {"available": True, "message": None},
                    "anomaly_detection": {"available": True, "message": None},
                    "ml_predictions": {"available": False, "message": "Unlocks in 15 days"},
                },
                "current_metrics": {
                    "hrv": 45.2,
                    "sleep_score": 78,
                    "resting_hr": 52,
                    "training_load_ratio": 1.1,
                },
                "observations": [
                    {
                        "category": "recovery",
                        "priority": "high",
                        "fact": "HRV is 13% below personal baseline",
                        "context": "Current: 45ms, Baseline: 52ms",
                        "trend": "declining",
                    }
                ],
            }
        }
