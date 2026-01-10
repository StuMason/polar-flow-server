"""User model for storing OAuth connections."""

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base, TimestampMixin, generate_uuid


class User(Base, TimestampMixin):
    """User with Polar OAuth connection.

    For self-hosted: One user per deployment
    For SaaS: Many users, managed by Laravel
    """

    __tablename__ = "users"

    # Primary key
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    # Polar user ID (from OAuth)
    polar_user_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    # OAuth tokens (encrypted at rest)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Optional user info
    email: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))

    # Connection status
    is_active: Mapped[bool] = mapped_column(default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        """String representation."""
        return f"<User(polar_user_id={self.polar_user_id}, is_active={self.is_active})>"
