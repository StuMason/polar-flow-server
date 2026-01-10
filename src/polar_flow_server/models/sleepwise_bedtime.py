"""SleepWise Circadian Bedtime data model."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base, TimestampMixin, UserScopedMixin, generate_uuid


class SleepWiseBedtime(Base, UserScopedMixin, TimestampMixin):
    """SleepWise Circadian Bedtime recommendation.

    Optimal sleep timing predictions based on circadian rhythm.
    user_id ensures data isolation for multi-tenancy.
    """

    __tablename__ = "sleepwise_bedtime"
    __table_args__ = (
        UniqueConstraint("user_id", "period_start_time", name="uq_sleepwise_bedtime_user_period"),
        {"comment": "SleepWise circadian bedtime recommendations"},
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    # Quality metrics
    validity: Mapped[str] = mapped_column(String(50), nullable=False)
    quality: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Quality assessment (e.g., CIRCADIAN_BEDTIME_QUALITY_COMPROMISED)",
    )
    result_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="HISTORY or PREDICTION",
    )

    # Time periods
    period_start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    period_end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Recommended sleep times
    preferred_sleep_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    preferred_sleep_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Sleep gate (optimal window)
    sleep_gate_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sleep_gate_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    sleep_timezone_offset_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<SleepWiseBedtime(user_id={self.user_id}, "
            f"quality={self.quality}, result_type={self.result_type})>"
        )
