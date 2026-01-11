"""Application settings model for DB storage."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base, TimestampMixin


class AppSettings(Base, TimestampMixin):
    """Application-level settings stored in database.

    For self-hosted: User configures via setup wizard
    For SaaS: Admin configures once, shared by all users

    Single row table - only one settings record exists.
    """

    __tablename__ = "app_settings"

    # Primary key (always id=1, singleton pattern)
    id: Mapped[int] = mapped_column(primary_key=True, default=1)

    # Polar OAuth app credentials
    polar_client_id: Mapped[str | None] = mapped_column(String(255))
    polar_client_secret_encrypted: Mapped[str | None] = mapped_column(Text)

    # Future: other app-level settings
    # site_name, contact_email, etc.

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<AppSettings(id={self.id}, client_id={'set' if self.polar_client_id else 'not set'})>"
        )
