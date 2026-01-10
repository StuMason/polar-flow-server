"""Nightly Recharge data model."""

from datetime import date
from typing import Any

from sqlalchemy import Date, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base, TimestampMixin, UserScopedMixin, generate_uuid


class NightlyRecharge(Base, UserScopedMixin, TimestampMixin):
    """Nightly Recharge data from Polar devices.

    ANS (Autonomic Nervous System) charge and recovery metrics.
    user_id ensures data isolation for multi-tenancy.
    """

    __tablename__ = "nightly_recharge"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_recharge_user_date"),
        {"comment": "Nightly Recharge with ANS charge and recovery status"},
    )

    # Primary key
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    # Recharge date
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # ANS charge (0-100)
    ans_charge: Mapped[float | None] = mapped_column(Float)
    ans_charge_status: Mapped[int | None] = mapped_column(
        Integer,
        comment="-3 to +3: much compromised to greatly above",
    )

    # HRV metrics
    hrv_avg: Mapped[float | None] = mapped_column(Float)
    hrv_status: Mapped[int | None] = mapped_column(Integer)

    # Breathing rate
    breathing_rate_avg: Mapped[float | None] = mapped_column(Float)
    breathing_rate_status: Mapped[int | None] = mapped_column(Integer)

    # Heart rate
    heart_rate_avg: Mapped[float | None] = mapped_column(Float)
    heart_rate_status: Mapped[int | None] = mapped_column(Integer)

    # Sleep
    sleep_score: Mapped[int | None] = mapped_column(Integer)
    sleep_charge: Mapped[float | None] = mapped_column(Float)
    sleep_charge_status: Mapped[int | None] = mapped_column(Integer)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<NightlyRecharge(user_id={self.user_id}, date={self.date}, "
            f"ans_charge={self.ans_charge})>"
        )

    @classmethod
    def from_polar_api(cls, user_id: str, data: dict[str, Any]) -> "NightlyRecharge":
        """Create NightlyRecharge instance from Polar API data.

        Args:
            user_id: User identifier (Polar user ID or Laravel UUID)
            data: Recharge data from Polar API

        Returns:
            NightlyRecharge instance ready to be saved
        """
        return cls(
            user_id=user_id,
            date=date.fromisoformat(data["date"]),
            ans_charge=data.get("ans_charge"),
            ans_charge_status=data.get("ans_charge_status"),
            hrv_avg=data.get("hrv_avg"),
            hrv_status=data.get("hrv_status"),
            breathing_rate_avg=data.get("breathing_rate_avg"),
            breathing_rate_status=data.get("breathing_rate_status"),
            heart_rate_avg=data.get("heart_rate_avg"),
            heart_rate_status=data.get("heart_rate_status"),
            sleep_score=data.get("sleep_score"),
            sleep_charge=data.get("sleep_charge"),
            sleep_charge_status=data.get("sleep_charge_status"),
        )
