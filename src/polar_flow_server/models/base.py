"""Base database model."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base model for all database tables."""

    pass


class TimestampMixin:
    """Mixin for created_at and updated_at timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class UserScopedMixin:
    """Mixin for user-scoped data.

    CRITICAL: All data tables must include user_id for multi-tenancy.
    This works for both self-hosted (one user_id) and SaaS (many user_ids).
    """

    user_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Polar user ID or Laravel user UUID",
    )


def generate_uuid() -> str:
    """Generate a UUID for primary keys."""
    return str(uuid4())
