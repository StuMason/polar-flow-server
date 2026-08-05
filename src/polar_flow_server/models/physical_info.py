"""Physical information model."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base, TimestampMixin, UserScopedMixin, generate_uuid


class PhysicalInfo(Base, UserScopedMixin, TimestampMixin):
    """Physical information snapshots from Polar (VO2 max, thresholds, weight).

    One row per Polar-side modification: syncs upsert on (user_id, recorded_at)
    where recorded_at is Polar's modified timestamp, so repeated syncs are
    idempotent while profile changes over time build a history (weight and
    VO2 max trends).
    """

    __tablename__ = "physical_info"
    __table_args__ = (
        UniqueConstraint("user_id", "recorded_at", name="uq_physical_info_user_recorded"),
        {"comment": "Physical info snapshots (VO2 max, HR thresholds, weight)"},
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    # Polar's modified (falling back to created) timestamp for this snapshot
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, comment="Polar modified timestamp"
    )

    weight_kg: Mapped[float | None] = mapped_column(Float)
    height_cm: Mapped[float | None] = mapped_column(Float)
    birthday: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(20))
    maximum_heart_rate: Mapped[int | None] = mapped_column(Integer, comment="bpm")
    resting_heart_rate: Mapped[int | None] = mapped_column(Integer, comment="bpm")
    aerobic_threshold: Mapped[int | None] = mapped_column(Integer, comment="bpm")
    anaerobic_threshold: Mapped[int | None] = mapped_column(Integer, comment="bpm")
    vo2_max: Mapped[int | None] = mapped_column(Integer, comment="ml/kg/min")
    weight_source: Mapped[str | None] = mapped_column(String(30))
    training_background: Mapped[str | None] = mapped_column(String(30))
    typical_day: Mapped[str | None] = mapped_column(String(30))
    sleep_goal_seconds: Mapped[int | None] = mapped_column(Integer)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<PhysicalInfo(user_id={self.user_id}, recorded_at={self.recorded_at}, "
            f"vo2_max={self.vo2_max})>"
        )
