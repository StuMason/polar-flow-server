"""SleepWise Alertness data model."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base, TimestampMixin, UserScopedMixin, generate_uuid


class SleepWiseAlertness(Base, UserScopedMixin, TimestampMixin):
    """SleepWise Alertness prediction data.

    Alertness predictions based on sleep patterns.
    user_id ensures data isolation for multi-tenancy.
    """

    __tablename__ = "sleepwise_alertness"
    __table_args__ = (
        UniqueConstraint("user_id", "period_start_time", name="uq_sleepwise_alertness_user_period"),
        {"comment": "SleepWise alertness predictions with hourly data"},
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    # Alertness grade metrics
    grade: Mapped[float] = mapped_column(Float, nullable=False)
    grade_validity_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    grade_type: Mapped[str] = mapped_column(String(50), nullable=False)
    grade_classification: Mapped[str] = mapped_column(String(50), nullable=False)
    validity: Mapped[str] = mapped_column(String(50), nullable=False)

    # Sleep-related metrics
    sleep_inertia: Mapped[str] = mapped_column(String(50), nullable=False)
    sleep_type: Mapped[str] = mapped_column(String(50), nullable=False)
    result_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Time periods
    period_start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    period_end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sleep_period_start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    sleep_period_end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sleep_timezone_offset_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    # Hourly data stored as JSON
    hourly_data_json: Mapped[str | None] = mapped_column(
        Text,
        comment="JSON array of hourly alertness predictions",
    )

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<SleepWiseAlertness(user_id={self.user_id}, "
            f"grade={self.grade}, classification={self.grade_classification})>"
        )
