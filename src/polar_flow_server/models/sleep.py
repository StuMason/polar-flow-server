"""Sleep data model."""

from datetime import date
from typing import Any

from sqlalchemy import Date, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base, TimestampMixin, UserScopedMixin, generate_uuid


class Sleep(Base, UserScopedMixin, TimestampMixin):
    """Sleep data from Polar devices.

    Stores comprehensive sleep metrics including stages, HRV, and quality scores.
    user_id ensures data isolation for multi-tenancy.
    """

    __tablename__ = "sleep"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_sleep_user_date"),
        {"comment": "Sleep data with HRV and sleep stages"},
    )

    # Primary key
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    # Sleep date (NOT a timestamp - it's the night's date)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Sleep times
    sleep_start_time: Mapped[str | None] = mapped_column(String(50))
    sleep_end_time: Mapped[str | None] = mapped_column(String(50))

    # Sleep duration (seconds)
    total_sleep_seconds: Mapped[int | None] = mapped_column(Integer)
    light_sleep_seconds: Mapped[int | None] = mapped_column(Integer)
    deep_sleep_seconds: Mapped[int | None] = mapped_column(Integer)
    rem_sleep_seconds: Mapped[int | None] = mapped_column(Integer)
    interruptions_seconds: Mapped[int | None] = mapped_column(Integer)

    # Sleep quality
    sleep_score: Mapped[int | None] = mapped_column(Integer)
    sleep_rating: Mapped[int | None] = mapped_column(Integer)

    # HRV metrics
    hrv_avg: Mapped[float | None] = mapped_column(Float)
    hrv_samples: Mapped[int | None] = mapped_column(Integer)

    # Heart rate
    heart_rate_avg: Mapped[float | None] = mapped_column(Float)
    heart_rate_min: Mapped[int | None] = mapped_column(Integer)
    heart_rate_max: Mapped[int | None] = mapped_column(Integer)

    # Breathing rate
    breathing_rate_avg: Mapped[float | None] = mapped_column(Float)

    # Temperature
    skin_temperature_avg: Mapped[float | None] = mapped_column(Float)

    def __repr__(self) -> str:
        """String representation."""
        return f"<Sleep(user_id={self.user_id}, date={self.date}, score={self.sleep_score})>"

    @classmethod
    def from_polar_api(cls, user_id: str, data: dict[str, Any]) -> "Sleep":
        """Create Sleep instance from Polar API data.

        Args:
            user_id: User identifier (Polar user ID or Laravel UUID)
            data: Sleep data from Polar API

        Returns:
            Sleep instance ready to be saved
        """
        return cls(
            user_id=user_id,
            date=date.fromisoformat(data["date"]),
            sleep_start_time=data.get("sleep_start_time"),
            sleep_end_time=data.get("sleep_end_time"),
            total_sleep_seconds=data.get("total_sleep_seconds"),
            light_sleep_seconds=data.get("light_sleep_seconds"),
            deep_sleep_seconds=data.get("deep_sleep_seconds"),
            rem_sleep_seconds=data.get("rem_sleep_seconds"),
            interruptions_seconds=data.get("interruptions_seconds"),
            sleep_score=data.get("sleep_score"),
            sleep_rating=data.get("sleep_rating"),
            hrv_avg=data.get("hrv_avg"),
            hrv_samples=data.get("hrv_samples"),
            heart_rate_avg=data.get("heart_rate_avg"),
            heart_rate_min=data.get("heart_rate_min"),
            heart_rate_max=data.get("heart_rate_max"),
            breathing_rate_avg=data.get("breathing_rate_avg"),
            skin_temperature_avg=data.get("skin_temperature_avg"),
        )
