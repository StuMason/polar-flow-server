"""Admin user model for dashboard authentication."""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base, TimestampMixin, generate_uuid


class AdminUser(Base, TimestampMixin):
    """Admin user for dashboard authentication.

    Self-hosted deployments typically have one admin user.
    Password is hashed using Argon2.
    """

    __tablename__ = "admin_users"

    # Primary key
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    # Credentials
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Optional name
    name: Mapped[str | None] = mapped_column(String(255))

    # Account status
    is_active: Mapped[bool] = mapped_column(default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        """String representation."""
        return f"<AdminUser(email={self.email}, is_active={self.is_active})>"
