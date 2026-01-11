"""SpO2 (Blood Oxygen) database model."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base, TimestampMixin, UserScopedMixin


class SpO2(Base, TimestampMixin, UserScopedMixin):
    """SpO2 (Blood Oxygen) test results.

    Stores blood oxygen measurements from Polar devices with
    SpO2 capability (e.g., Polar Loop).
    """

    __tablename__ = "spo2"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Measurement identifiers
    device_id: Mapped[str] = mapped_column(String(100), nullable=False)
    test_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone_offset_minutes: Mapped[int] = mapped_column(Integer, default=0)

    # Core SpO2 metrics
    blood_oxygen_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="SpO2 percentage (0-100)"
    )
    spo2_class: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Classification: NORMAL, LOW, etc."
    )
    spo2_deviation: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="Deviation from baseline"
    )

    # Quality metrics
    quality_percent: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="Signal quality percentage"
    )

    # Heart metrics during test
    avg_heart_rate: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Average HR during SpO2 test"
    )
    hrv_ms: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="HRV during test in ms"
    )
    hrv_deviation: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="HRV deviation from baseline"
    )

    # Environment
    altitude_meters: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="Altitude during measurement"
    )

    # Status
    test_status: Mapped[str] = mapped_column(
        String(50), default="COMPLETED", comment="Test completion status"
    )

    __table_args__ = (
        # Unique constraint: one test per user per timestamp
        {"sqlite_autoincrement": True},
    )

    # For upsert operations
    __upsert_index_elements__ = ["user_id", "test_time"]
