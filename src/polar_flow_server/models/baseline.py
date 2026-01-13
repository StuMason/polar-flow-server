"""User baseline analytics model."""

from datetime import date, datetime
from enum import Enum

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base, TimestampMixin, UserScopedMixin, generate_uuid


class MetricName(str, Enum):
    """Canonical metric names for baselines.

    Using an enum prevents typos and ensures consistency.
    """

    HRV_RMSSD = "hrv_rmssd"
    SLEEP_SCORE = "sleep_score"
    RESTING_HR = "resting_hr"
    TRAINING_LOAD = "training_load"
    TRAINING_LOAD_RATIO = "training_load_ratio"
    ACTIVE_CALORIES = "active_calories"
    SLEEP_CONSISTENCY = "sleep_consistency"
    STEPS = "steps"


class BaselineStatus(str, Enum):
    """Status of a baseline calculation."""

    READY = "ready"  # Full data available
    PARTIAL = "partial"  # Some data, not all periods
    INSUFFICIENT = "insufficient"  # Not enough data


class UserBaseline(Base, UserScopedMixin, TimestampMixin):
    """Computed personal baselines for health metrics.

    Stores rolling averages and statistics calculated from historical data.
    Baselines are user-specific and metric-specific.

    user_id ensures data isolation for multi-tenancy.
    """

    __tablename__ = "user_baselines"
    __table_args__ = (
        UniqueConstraint("user_id", "metric_name", name="uq_user_baseline"),
        {"comment": "User-specific baseline calculations for analytics"},
    )

    # Primary key
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    # Metric identification
    metric_name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Metric identifier (hrv_rmssd, sleep_score, etc.)",
    )

    # Baseline values (calculated from historical data)
    baseline_value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="Overall baseline (all available data)",
    )
    baseline_7d: Mapped[float | None] = mapped_column(
        Float,
        comment="7-day rolling average",
    )
    baseline_30d: Mapped[float | None] = mapped_column(
        Float,
        comment="30-day rolling average",
    )
    baseline_90d: Mapped[float | None] = mapped_column(
        Float,
        comment="90-day rolling average",
    )

    # Statistics for anomaly detection
    std_dev: Mapped[float | None] = mapped_column(
        Float,
        comment="Standard deviation",
    )
    median_value: Mapped[float | None] = mapped_column(
        Float,
        comment="Median value (for IQR calculations)",
    )
    q1: Mapped[float | None] = mapped_column(
        Float,
        comment="25th percentile (Q1)",
    )
    q3: Mapped[float | None] = mapped_column(
        Float,
        comment="75th percentile (Q3)",
    )
    min_value: Mapped[float | None] = mapped_column(
        Float,
        comment="Minimum observed value",
    )
    max_value: Mapped[float | None] = mapped_column(
        Float,
        comment="Maximum observed value",
    )

    # Data quality
    sample_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="Number of data points used",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=BaselineStatus.INSUFFICIENT.value,
        comment="Calculation status (ready, partial, insufficient)",
    )

    # Data range
    data_start_date: Mapped[date | None] = mapped_column(
        Date,
        comment="Earliest data point date",
    )
    data_end_date: Mapped[date | None] = mapped_column(
        Date,
        comment="Latest data point date",
    )

    # Calculation metadata
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When this baseline was last calculated",
    )

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<UserBaseline(user_id={self.user_id}, metric={self.metric_name}, "
            f"baseline={self.baseline_value:.2f}, status={self.status})>"
        )

    @property
    def iqr(self) -> float | None:
        """Interquartile range (Q3 - Q1)."""
        if self.q1 is not None and self.q3 is not None:
            return self.q3 - self.q1
        return None

    @property
    def lower_bound(self) -> float | None:
        """Lower bound for anomaly detection (Q1 - 1.5*IQR)."""
        if self.q1 is not None and self.iqr is not None:
            return self.q1 - 1.5 * self.iqr
        return None

    @property
    def upper_bound(self) -> float | None:
        """Upper bound for anomaly detection (Q3 + 1.5*IQR)."""
        if self.q3 is not None and self.iqr is not None:
            return self.q3 + 1.5 * self.iqr
        return None

    def is_anomaly(self, value: float) -> tuple[bool, str | None]:
        """Check if a value is an anomaly based on IQR bounds.

        Args:
            value: The value to check

        Returns:
            Tuple of (is_anomaly, severity) where severity is 'warning' or 'critical'
        """
        if self.lower_bound is None or self.upper_bound is None:
            return False, None

        # Extreme bounds (3 * IQR)
        if self.iqr is not None:
            extreme_lower = self.q1 - 3 * self.iqr  # type: ignore
            extreme_upper = self.q3 + 3 * self.iqr  # type: ignore

            if value < extreme_lower or value > extreme_upper:
                return True, "critical"

        # Standard bounds (1.5 * IQR)
        if value < self.lower_bound or value > self.upper_bound:
            return True, "warning"

        return False, None
