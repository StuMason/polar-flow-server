"""API Key model for service-to-service authentication."""

from datetime import datetime

# Avoid circular import - use TYPE_CHECKING for type hints only
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from polar_flow_server.models.base import Base

if TYPE_CHECKING:
    from polar_flow_server.models.user import User


class APIKey(Base):
    """API key for authenticating service-to-service requests.

    Supports two modes:
    - Service-level keys (user_id=None): Full access to all data
    - User-scoped keys (user_id set): Access only to that user's data

    Keys are stored as SHA-256 hashes for security.

    Attributes:
        id: Auto-incrementing primary key
        key_hash: SHA-256 hash of the actual API key
        key_prefix: First 8 chars of key for identification (e.g., "pfk_a1b2")
        name: Human-readable name for the key (e.g., "Laravel Production")
        user_id: Optional FK to users.polar_user_id for user-scoped keys
        is_active: Whether the key is currently valid
        rate_limit_requests: Max requests per hour for this key
        rate_limit_remaining: Remaining requests in current window
        rate_limit_reset_at: When the rate limit window resets
        created_at: When the key was created
        last_used_at: Last time the key was used for authentication
    """

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(12), index=True, default="")
    name: Mapped[str] = mapped_column(String(100))

    # User scoping (nullable for service-level keys)
    user_id: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey("users.polar_user_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    is_active: Mapped[bool] = mapped_column(default=True, index=True)

    # Rate limiting
    rate_limit_requests: Mapped[int] = mapped_column(Integer, default=1000)
    rate_limit_remaining: Mapped[int] = mapped_column(Integer, default=1000)
    rate_limit_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationship to User (optional - only for user-scoped keys)
    user: Mapped["User | None"] = relationship("User", back_populates="api_keys", lazy="selectin")

    def __repr__(self) -> str:
        """Return string representation."""
        scope = f"user={self.user_id}" if self.user_id else "service-level"
        return f"<APIKey(id={self.id}, name='{self.name}', {scope}, active={self.is_active})>"

    @property
    def is_user_scoped(self) -> bool:
        """Return True if this key is scoped to a specific user."""
        return self.user_id is not None

    @property
    def is_service_level(self) -> bool:
        """Return True if this is a service-level key with full access."""
        return self.user_id is None
