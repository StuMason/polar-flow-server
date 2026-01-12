"""Temporary authorization code model for secure OAuth exchange."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base

# Default expiration time for temp codes (5 minutes)
TEMP_CODE_EXPIRY_MINUTES = 5


class TempAuthCode(Base):
    """Temporary authorization code for secure API key exchange.

    After successful OAuth with Polar, a temporary code is generated and
    passed back to the client via redirect URL. The client then exchanges
    this code server-to-server for the actual API key.

    This prevents API keys from appearing in:
    - Browser history
    - Server logs
    - Referrer headers

    Attributes:
        id: Auto-incrementing primary key
        code_hash: SHA-256 hash of the temporary code
        user_id: FK to the user this code will generate a key for
        client_id: Optional client identifier for validation
        is_used: Whether the code has been exchanged (single-use)
        created_at: When the code was created
        expires_at: When the code expires (default: 5 minutes)
    """

    __tablename__ = "temp_auth_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("users.polar_user_id", ondelete="CASCADE"),
        index=True,
    )
    client_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_used: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        """Return string representation."""
        status = "used" if self.is_used else "pending"
        return f"<TempAuthCode(id={self.id}, user_id={self.user_id}, status={status})>"

    @property
    def is_expired(self) -> bool:
        """Return True if this code has expired."""
        return datetime.now(UTC) > self.expires_at

    @property
    def is_valid(self) -> bool:
        """Return True if this code can be used for exchange."""
        return not self.is_used and not self.is_expired

    @classmethod
    def calculate_expiry(cls) -> datetime:
        """Calculate the expiry time for a new code."""
        return datetime.now(UTC) + timedelta(minutes=TEMP_CODE_EXPIRY_MINUTES)
