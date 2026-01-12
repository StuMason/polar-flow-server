"""API Key model for service-to-service authentication."""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base


class APIKey(Base):
    """API key for authenticating service-to-service requests.

    Used by Laravel or other clients to securely access polar-flow-server
    data endpoints. Keys are stored as SHA-256 hashes for security.

    Attributes:
        id: Auto-incrementing primary key
        key_hash: SHA-256 hash of the actual API key
        name: Human-readable name for the key (e.g., "Laravel Production")
        is_active: Whether the key is currently valid
        created_at: When the key was created
        last_used_at: Last time the key was used for authentication
    """

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        """Return string representation."""
        return f"<APIKey(id={self.id}, name='{self.name}', active={self.is_active})>"
