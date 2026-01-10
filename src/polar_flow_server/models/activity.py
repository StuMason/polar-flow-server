"""Daily activity data model."""

from datetime import date
from typing import Any

from sqlalchemy import Date, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base, TimestampMixin, UserScopedMixin, generate_uuid


class Activity(Base, UserScopedMixin, TimestampMixin):
    """Daily activity data from Polar devices.

    Steps, calories, active time, and activity zones.
    user_id ensures data isolation for multi-tenancy.
    """

    __tablename__ = "activity"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_activity_user_date"),
        {"comment": "Daily activity with steps, calories, and zones"},
    )

    # Primary key
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    # Activity date
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Steps and distance
    steps: Mapped[int | None] = mapped_column(Integer)
    distance_meters: Mapped[float | None] = mapped_column(Float)

    # Calories
    calories_active: Mapped[int | None] = mapped_column(Integer)
    calories_total: Mapped[int | None] = mapped_column(Integer)

    # Active time (seconds)
    active_time_seconds: Mapped[int | None] = mapped_column(Integer)

    # Activity score
    activity_score: Mapped[int | None] = mapped_column(Integer)

    # Inactivity alerts
    inactivity_alerts: Mapped[int | None] = mapped_column(Integer)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<Activity(user_id={self.user_id}, date={self.date}, "
            f"steps={self.steps}, calories={self.calories_total})>"
        )

    @classmethod
    def from_polar_api(cls, user_id: str, data: dict[str, Any]) -> "Activity":
        """Create Activity instance from Polar API data.

        Args:
            user_id: User identifier (Polar user ID or Laravel UUID)
            data: Activity data from Polar API

        Returns:
            Activity instance ready to be saved
        """
        return cls(
            user_id=user_id,
            date=date.fromisoformat(data["date"]),
            steps=data.get("steps"),
            distance_meters=data.get("distance_meters"),
            calories_active=data.get("calories_active"),
            calories_total=data.get("calories_total"),
            active_time_seconds=data.get("active_time_seconds"),
            activity_score=data.get("activity_score"),
            inactivity_alerts=data.get("inactivity_alerts"),
        )
