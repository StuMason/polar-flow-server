"""Activity Samples data model."""

from datetime import date

from sqlalchemy import Date, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base, TimestampMixin, UserScopedMixin, generate_uuid


class ActivitySamples(Base, UserScopedMixin, TimestampMixin):
    """Daily activity samples with minute-by-minute step data.

    Contains step samples throughout the day at 1-minute intervals.
    user_id ensures data isolation for multi-tenancy.
    """

    __tablename__ = "activity_samples"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_activity_samples_user_date"),
        {"comment": "Minute-by-minute activity samples with step data"},
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Summary metrics
    total_steps: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Total steps for the day"
    )
    interval_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Sample interval (60000ms = 1 minute)"
    )
    sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Number of samples in the day"
    )

    # Raw samples stored as JSON for detailed analysis
    samples_json: Mapped[str | None] = mapped_column(
        Text,
        comment="JSON array of step samples with timestamps",
    )

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<ActivitySamples(user_id={self.user_id}, date={self.date}, "
            f"total_steps={self.total_steps}, samples={self.sample_count})>"
        )
