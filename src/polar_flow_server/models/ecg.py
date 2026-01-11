"""ECG (Electrocardiogram) database model."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base, TimestampMixin, UserScopedMixin


class ECG(Base, TimestampMixin, UserScopedMixin):
    """ECG test results with waveform data.

    Stores ECG measurements from Polar devices with ECG capability.
    Waveform samples are stored as JSON for flexibility.
    """

    __tablename__ = "ecg"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Measurement identifiers
    device_id: Mapped[str] = mapped_column(String(100), nullable=False)
    test_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone_offset_minutes: Mapped[int] = mapped_column(Integer, default=0)

    # Heart rate metrics
    avg_heart_rate: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Average HR during ECG test"
    )
    hrv_ms: Mapped[float] = mapped_column(Float, nullable=False, comment="HRV (RMSSD) in ms")
    hrv_level: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="HRV classification: LOW, NORMAL, HIGH"
    )
    rri_ms: Mapped[float] = mapped_column(Float, nullable=False, comment="R-R interval in ms")

    # Pulse Transit Time (for compatible devices)
    ptt_systolic_ms: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="PTT systolic"
    )
    ptt_diastolic_ms: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="PTT diastolic"
    )
    ptt_quality_index: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="PTT quality index"
    )

    # Waveform data (stored as JSON)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, comment="Number of ECG samples")
    samples_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="ECG waveform samples as JSON"
    )
    quality_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Quality measurements over time as JSON"
    )

    # Duration
    duration_seconds: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="Test duration in seconds"
    )

    __table_args__ = ({"sqlite_autoincrement": True},)

    # For upsert operations
    __upsert_index_elements__ = ["user_id", "test_time"]
