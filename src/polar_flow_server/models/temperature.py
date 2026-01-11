"""Temperature database models (Body and Skin)."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base, TimestampMixin, UserScopedMixin


class BodyTemperature(Base, TimestampMixin, UserScopedMixin):
    """Body temperature measurement periods.

    Stores continuous temperature monitoring data with samples.
    """

    __tablename__ = "body_temperature"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Measurement identifiers
    device_id: Mapped[str] = mapped_column(String(100), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Measurement context
    measurement_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="e.g., CONTINUOUS, SPOT"
    )
    sensor_location: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="e.g., WRIST, FINGER"
    )

    # Aggregated metrics (computed from samples)
    temp_min: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="Minimum temperature (Celsius)"
    )
    temp_max: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="Maximum temperature (Celsius)"
    )
    temp_avg: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="Average temperature (Celsius)"
    )

    # Sample data
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    samples_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Temperature samples as JSON"
    )

    __table_args__ = ({"sqlite_autoincrement": True},)

    # For upsert operations
    __upsert_index_elements__ = ["user_id", "start_time"]


class SkinTemperature(Base, TimestampMixin, UserScopedMixin):
    """Sleep-time skin temperature with baseline deviation.

    Simpler than body temperature - single value per night with
    deviation from user's established baseline.
    """

    __tablename__ = "skin_temperature"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Date reference
    sleep_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Temperature metrics
    temperature_celsius: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Skin temperature during sleep"
    )
    deviation_from_baseline: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Deviation from baseline (Celsius)"
    )

    # Derived status (can be used for alerts)
    is_elevated: Mapped[bool] = mapped_column(
        Integer, default=False, comment="Temperature > 0.5C above baseline"
    )

    __table_args__ = (
        # Unique constraint: one record per user per night
        {"sqlite_autoincrement": True},
    )

    # For upsert operations
    __upsert_index_elements__ = ["user_id", "sleep_date"]
