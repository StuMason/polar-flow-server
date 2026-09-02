"""Add OAuth 2.1 authorization-server tables for the MCP connector flow.

Revision ID: g8h9i0j1k2l3
Revises: f7g8h9i0j1k2
Create Date: 2026-08-04 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g8h9i0j1k2l3"
down_revision: str | None = "f7g8h9i0j1k2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create oauth_clients, oauth_auth_codes, and oauth_tokens tables."""
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.String(64), primary_key=True),
        sa.Column(
            "client_metadata",
            sa.JSON(),
            nullable=False,
            comment="Full RFC 7591 client metadata, revalidated on load",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "oauth_auth_codes",
        sa.Column("code_hash", sa.String(64), primary_key=True, comment="SHA-256 of the code"),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False, comment="polar_user_id"),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False, comment="Unix seconds"),
        sa.Column("code_challenge", sa.String(255), nullable=False, comment="PKCE S256 challenge"),
        sa.Column("redirect_uri", sa.String(1024), nullable=False),
        sa.Column("redirect_uri_provided_explicitly", sa.Boolean(), nullable=False, default=True),
        sa.Column("resource", sa.String(1024), nullable=True),
    )

    op.create_table(
        "oauth_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True, comment="SHA-256 of the token"),
        sa.Column("token_type", sa.String(10), nullable=False, comment="access or refresh"),
        sa.Column(
            "pair_id",
            sa.String(36),
            nullable=False,
            index=True,
            comment="Access+refresh issued together share this; revocation hits the pair",
        ),
        sa.Column("client_id", sa.String(64), nullable=False, index=True),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column(
            "expires_at", sa.Float(), nullable=True, comment="Unix seconds, null = no expiry"
        ),
        sa.Column("revoked", sa.Boolean(), nullable=False, default=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    """Drop the OAuth tables."""
    op.drop_table("oauth_tokens")
    op.drop_table("oauth_auth_codes")
    op.drop_table("oauth_clients")
