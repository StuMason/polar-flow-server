"""OAuth 2.1 authorization-server storage for the MCP connector flow.

polar-flow-server acts as its own OAuth authorization server so MCP clients
(Claude Desktop and friends) can "Connect" with a real sign-in instead of a
pasted API key. Clients arrive via Dynamic Client Registration, the admin
approves a consent screen, and the issued tokens map to the same user scope
as user-scoped API keys.

Codes and tokens are stored as SHA-256 hashes; raw values never touch disk.
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base


class OAuthClient(Base):
    """A dynamically-registered OAuth client (RFC 7591)."""

    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Full OAuthClientInformationFull payload, revalidated on load
    client_metadata: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OAuthAuthCode(Base):
    """A single-use authorization code awaiting exchange."""

    __tablename__ = "oauth_auth_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)  # polar_user_id
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)  # unix seconds
    code_challenge: Mapped[str] = mapped_column(String(255), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(Boolean, default=True)
    resource: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class OAuthIssuedToken(Base):
    """An issued access or refresh token.

    Access and refresh tokens issued together share a pair_id so revoking
    either revokes both (OAuth 2.1 SHOULD), and refresh rotation retires the
    whole pair.
    """

    __tablename__ = "oauth_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_type: Mapped[str] = mapped_column(String(10), nullable=False)  # access | refresh
    pair_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    expires_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
