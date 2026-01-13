"""Pattern analysis model for correlations and composite scores."""

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base, TimestampMixin, UserScopedMixin, generate_uuid


class PatternType(str, Enum):
    """Types of patterns that can be detected."""

    CORRELATION = "correlation"  # Statistical correlation between metrics
    TREND = "trend"  # Directional change over time
    COMPOSITE = "composite"  # Multi-metric score (e.g., overtraining risk)
    ANOMALY = "anomaly"  # Detected anomaly pattern
    CONSISTENCY = "consistency"  # Behavioral consistency (e.g., sleep timing)


class PatternName(str, Enum):
    """Canonical pattern names for consistent reference."""

    # Correlations
    SLEEP_HRV_CORRELATION = "sleep_hrv_correlation"
    TRAINING_RECOVERY_LAG = "training_recovery_lag"
    ACTIVITY_SLEEP_CORRELATION = "activity_sleep_correlation"

    # Composite scores
    OVERTRAINING_RISK = "overtraining_risk"
    RECOVERY_READINESS = "recovery_readiness"

    # Consistency patterns
    SLEEP_TIMING_CONSISTENCY = "sleep_timing_consistency"
    TRAINING_CONSISTENCY = "training_consistency"

    # Trends
    HRV_TREND = "hrv_trend"
    SLEEP_TREND = "sleep_trend"
    FITNESS_TREND = "fitness_trend"


class Significance(str, Enum):
    """Statistical significance levels."""

    HIGH = "high"  # p < 0.01 or risk >= 50
    MEDIUM = "medium"  # p < 0.05 or risk >= 25
    LOW = "low"  # p >= 0.05 or risk < 25
    INSUFFICIENT = "insufficient"  # Not enough data


class PatternAnalysis(Base, UserScopedMixin, TimestampMixin):
    """Detected patterns and correlations for a user.

    Stores statistical analyses including correlations, trends,
    and composite risk scores computed from user health data.
    """

    __tablename__ = "pattern_analyses"
    __table_args__ = (
        UniqueConstraint("user_id", "pattern_type", "pattern_name", name="uq_user_pattern"),
        {"comment": "Detected patterns and correlations for analytics"},
    )

    # Primary key
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    # Pattern identification
    pattern_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Type of pattern (correlation, trend, composite, etc.)",
    )
    pattern_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Specific pattern identifier (e.g., sleep_hrv_correlation)",
    )

    # Metrics involved (stored as JSON array)
    metrics_involved: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: [],  # Explicit factory to avoid mutable default concerns
        comment="List of metrics used in this analysis",
    )

    # Analysis window
    analysis_window_days: Mapped[int] = mapped_column(
        Integer,
        default=30,
        comment="Number of days of data used in analysis",
    )

    # Results
    score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Primary score (correlation coefficient, risk score, etc.)",
    )
    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Confidence level (1 - p_value for correlations)",
    )
    significance: Mapped[str] = mapped_column(
        String(20),
        default=Significance.INSUFFICIENT.value,
        comment="Statistical significance (high, medium, low, insufficient)",
    )

    # Detailed results (JSON blob for flexibility)
    details: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Additional analysis details (interpretation, factors, etc.)",
    )

    # Sample info
    sample_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Number of data points used in analysis",
    )

    # Timestamps
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When this analysis was performed",
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When this analysis expires (null = valid until recalculated)",
    )

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<PatternAnalysis(user_id={self.user_id}, "
            f"pattern={self.pattern_name}, score={self.score:.2f if self.score else 'N/A'})>"
        )

    @property
    def is_significant(self) -> bool:
        """Check if pattern has high or medium significance."""
        return self.significance in (Significance.HIGH.value, Significance.MEDIUM.value)

    @property
    def interpretation(self) -> str | None:
        """Get human-readable interpretation from details."""
        if self.details and "interpretation" in self.details:
            value = self.details["interpretation"]
            if isinstance(value, str):
                return value
        return None
