"""Continuous Heart Rate data model."""

from datetime import date

from sqlalchemy import Date, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base, TimestampMixin, UserScopedMixin, generate_uuid


class ContinuousHeartRate(Base, UserScopedMixin, TimestampMixin):
    """Continuous heart rate data for a day.

    Contains 5-minute interval heart rate samples throughout the day.
    user_id ensures data isolation for multi-tenancy.
    """

    __tablename__ = "continuous_heart_rate"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_continuous_hr_user_date"),
        {"comment": "All-day heart rate samples at 5-minute intervals"},
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Aggregated metrics for quick dashboard display
    sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Number of HR samples"
    )
    hr_min: Mapped[int | None] = mapped_column(Integer, comment="Minimum heart rate")
    hr_max: Mapped[int | None] = mapped_column(Integer, comment="Maximum heart rate")
    hr_avg: Mapped[int | None] = mapped_column(Integer, comment="Average heart rate")

    # Raw samples stored as JSON for detailed analysis
    samples_json: Mapped[str | None] = mapped_column(
        Text,
        comment="JSON array of HR samples with timestamps",
    )

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<ContinuousHeartRate(user_id={self.user_id}, date={self.date}, "
            f"samples={self.sample_count}, avg={self.hr_avg})>"
        )
