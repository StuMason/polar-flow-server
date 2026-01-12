"""Add per-user API keys and temp auth codes

Revision ID: c4d5e6f7g8h9
Revises: b2c3d4e5f678
Create Date: 2026-01-12

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7g8h9"
down_revision: str | Sequence[str] | None = "b2c3d4e5f678"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add new columns to api_keys table
    op.add_column(
        "api_keys",
        sa.Column("key_prefix", sa.String(length=12), nullable=False, server_default=""),
    )
    op.add_column(
        "api_keys",
        sa.Column(
            "user_id",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.add_column(
        "api_keys",
        sa.Column("rate_limit_requests", sa.Integer(), nullable=False, server_default="1000"),
    )
    op.add_column(
        "api_keys",
        sa.Column("rate_limit_remaining", sa.Integer(), nullable=False, server_default="1000"),
    )
    op.add_column(
        "api_keys",
        sa.Column("rate_limit_reset_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Add indexes for api_keys
    op.create_index(op.f("ix_api_keys_key_prefix"), "api_keys", ["key_prefix"], unique=False)
    op.create_index(op.f("ix_api_keys_user_id"), "api_keys", ["user_id"], unique=False)
    op.create_index(op.f("ix_api_keys_is_active"), "api_keys", ["is_active"], unique=False)

    # Add foreign key constraint for user_id
    op.create_foreign_key(
        "fk_api_keys_user_id",
        "api_keys",
        "users",
        ["user_id"],
        ["polar_user_id"],
        ondelete="CASCADE",
    )

    # Create temp_auth_codes table
    op.create_table(
        "temp_auth_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("client_id", sa.String(length=100), nullable=True),
        sa.Column("is_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.polar_user_id"],
            name="fk_temp_auth_codes_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_temp_auth_codes_code_hash"), "temp_auth_codes", ["code_hash"], unique=True
    )
    op.create_index(
        op.f("ix_temp_auth_codes_user_id"), "temp_auth_codes", ["user_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop temp_auth_codes table
    op.drop_index(op.f("ix_temp_auth_codes_user_id"), table_name="temp_auth_codes")
    op.drop_index(op.f("ix_temp_auth_codes_code_hash"), table_name="temp_auth_codes")
    op.drop_table("temp_auth_codes")

    # Drop foreign key and indexes from api_keys
    op.drop_constraint("fk_api_keys_user_id", "api_keys", type_="foreignkey")
    op.drop_index(op.f("ix_api_keys_is_active"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_user_id"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_key_prefix"), table_name="api_keys")

    # Drop new columns from api_keys
    op.drop_column("api_keys", "rate_limit_reset_at")
    op.drop_column("api_keys", "rate_limit_remaining")
    op.drop_column("api_keys", "rate_limit_requests")
    op.drop_column("api_keys", "user_id")
    op.drop_column("api_keys", "key_prefix")
