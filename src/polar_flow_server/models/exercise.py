"""Exercise/workout data model."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base, TimestampMixin, UserScopedMixin, generate_uuid


class Exercise(Base, UserScopedMixin, TimestampMixin):
    """Exercise/workout data from Polar devices.

    Detailed workout metrics including duration, heart rate, pace, distance, etc.
    user_id ensures data isolation for multi-tenancy.
    """

    __tablename__ = "exercise"
    __table_args__ = (
        UniqueConstraint("user_id", "polar_exercise_id", name="uq_exercise_user_polar_id"),
        {"comment": "Exercise/workout data with detailed metrics"},
    )

    # Primary key
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    # Polar's exercise ID (from API)
    polar_exercise_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    # Exercise timing
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    stop_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)

    # Sport type
    sport: Mapped[str | None] = mapped_column(String(100))
    detailed_sport_info: Mapped[str | None] = mapped_column(String(255))

    # Distance and pace
    distance_meters: Mapped[float | None] = mapped_column(Float)
    average_speed_mps: Mapped[float | None] = mapped_column(Float)
    max_speed_mps: Mapped[float | None] = mapped_column(Float)

    # Heart rate
    average_heart_rate: Mapped[int | None] = mapped_column(Integer)
    max_heart_rate: Mapped[int | None] = mapped_column(Integer)
    min_heart_rate: Mapped[int | None] = mapped_column(Integer)

    # Calories and training load
    calories: Mapped[int | None] = mapped_column(Integer)
    training_load: Mapped[float | None] = mapped_column(Float)

    # Ascent/descent (for running, cycling)
    ascent_meters: Mapped[float | None] = mapped_column(Float)
    descent_meters: Mapped[float | None] = mapped_column(Float)

    # Cadence
    average_cadence: Mapped[float | None] = mapped_column(Float)
    max_cadence: Mapped[int | None] = mapped_column(Integer)

    # Power (for cycling)
    average_power: Mapped[float | None] = mapped_column(Float)
    max_power: Mapped[int | None] = mapped_column(Integer)

    # Notes/description
    notes: Mapped[str | None] = mapped_column(Text)

    # Has GPS data flag
    has_route: Mapped[bool] = mapped_column(default=False)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<Exercise(user_id={self.user_id}, sport={self.sport}, "
            f"start={self.start_time}, duration={self.duration_seconds}s)>"
        )

    @classmethod
    def from_polar_api(cls, user_id: str, data: dict[str, Any]) -> "Exercise":
        """Create Exercise instance from Polar API data.

        Args:
            user_id: User identifier (Polar user ID or Laravel UUID)
            data: Exercise data from Polar API

        Returns:
            Exercise instance ready to be saved
        """
        return cls(
            user_id=user_id,
            polar_exercise_id=data["id"],
            start_time=datetime.fromisoformat(data["start_time"].replace("Z", "+00:00")),
            stop_time=(
                datetime.fromisoformat(data["stop_time"].replace("Z", "+00:00"))
                if data.get("stop_time")
                else None
            ),
            duration_seconds=data.get("duration_seconds"),
            sport=data.get("sport"),
            detailed_sport_info=data.get("detailed_sport_info"),
            distance_meters=data.get("distance_meters"),
            average_speed_mps=data.get("average_speed_mps"),
            max_speed_mps=data.get("max_speed_mps"),
            average_heart_rate=data.get("average_heart_rate"),
            max_heart_rate=data.get("max_heart_rate"),
            min_heart_rate=data.get("min_heart_rate"),
            calories=data.get("calories"),
            training_load=data.get("training_load"),
            ascent_meters=data.get("ascent_meters"),
            descent_meters=data.get("descent_meters"),
            average_cadence=data.get("average_cadence"),
            max_cadence=data.get("max_cadence"),
            average_power=data.get("average_power"),
            max_power=data.get("max_power"),
            notes=data.get("notes"),
            has_route=data.get("has_route", False),
        )
