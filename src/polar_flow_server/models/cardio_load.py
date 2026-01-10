"""Cardio Load data model."""

from datetime import date

from sqlalchemy import Date, Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base, TimestampMixin, UserScopedMixin, generate_uuid


class CardioLoad(Base, UserScopedMixin, TimestampMixin):
    """Cardio Load data from Polar devices.

    Training load and recovery metrics including strain and tolerance.
    Data available for last 28 days.
    user_id ensures data isolation for multi-tenancy.
    """

    __tablename__ = "cardio_load"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_cardio_load_user_date"),
        {"comment": "Cardio load with strain, tolerance, and load distribution"},
    )

    # Primary key
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    # Date
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Core cardio load metrics
    cardio_load: Mapped[float | None] = mapped_column(
        Float,
        comment="Overall cardio load value (-1.0 if not available)",
    )
    cardio_load_status: Mapped[str | None] = mapped_column(
        String(50),
        comment="Load status (e.g., LOAD_STATUS_NOT_AVAILABLE)",
    )
    cardio_load_ratio: Mapped[float | None] = mapped_column(
        Float,
        comment="Load ratio (-1.0 if not available)",
    )

    # Strain and tolerance
    strain: Mapped[float | None] = mapped_column(Float, comment="Training strain value")
    tolerance: Mapped[float | None] = mapped_column(
        Float,
        comment="Training tolerance value (-1.0 if not available)",
    )

    # Load distribution across intensity levels
    load_very_low: Mapped[float | None] = mapped_column(
        Float,
        comment="Very low intensity load",
    )
    load_low: Mapped[float | None] = mapped_column(Float, comment="Low intensity load")
    load_medium: Mapped[float | None] = mapped_column(Float, comment="Medium intensity load")
    load_high: Mapped[float | None] = mapped_column(Float, comment="High intensity load")
    load_very_high: Mapped[float | None] = mapped_column(
        Float,
        comment="Very high intensity load",
    )

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<CardioLoad(user_id={self.user_id}, date={self.date}, "
            f"strain={self.strain}, tolerance={self.tolerance})>"
        )
