"""Add sync_logs table for comprehensive sync audit trail.

Revision ID: f7g8h9i0j1k2
Revises: e6f7g8h9i0j1
Create Date: 2026-01-13 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7g8h9i0j1k2"
down_revision: str | None = "e6f7g8h9i0j1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create sync_logs table for complete sync audit trail."""
    op.create_table(
        "sync_logs",
        # Primary key
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # User identification
        sa.Column(
            "user_id",
            sa.String(255),
            nullable=False,
            index=True,
            comment="User being synced (Polar user ID or Laravel UUID)",
        ),
        sa.Column(
            "job_id",
            sa.String(36),
            nullable=False,
            index=True,
            comment="UUID for correlating logs across services",
        ),
        # Timing
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            index=True,
            comment="When sync began",
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When sync finished (null if still running)",
        ),
        sa.Column(
            "duration_ms",
            sa.Integer(),
            nullable=True,
            comment="Total sync duration in milliseconds",
        ),
        # Status
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="started",
            index=True,
            comment="Status: started, success, partial, failed, skipped",
        ),
        # Error tracking
        sa.Column(
            "error_type",
            sa.String(50),
            nullable=True,
            index=True,
            comment="Categorized error type (token_expired, rate_limited_15m, etc.)",
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
            comment="Human-readable error description",
        ),
        sa.Column(
            "error_details",
            JSON(),
            nullable=True,
            comment="Full error context as JSON",
        ),
        # Results
        sa.Column(
            "records_synced",
            JSON(),
            nullable=True,
            comment="Count of records synced per data type",
        ),
        sa.Column(
            "api_calls_made",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Total API calls made during sync",
        ),
        # Rate limit tracking
        sa.Column(
            "rate_limit_remaining_15m",
            sa.Integer(),
            nullable=True,
            comment="Remaining 15-min quota after sync",
        ),
        sa.Column(
            "rate_limit_remaining_24h",
            sa.Integer(),
            nullable=True,
            comment="Remaining 24-hour quota after sync",
        ),
        sa.Column(
            "rate_limit_limit_15m",
            sa.Integer(),
            nullable=True,
            comment="Max requests in 15-min window",
        ),
        sa.Column(
            "rate_limit_limit_24h",
            sa.Integer(),
            nullable=True,
            comment="Max requests in 24-hour window",
        ),
        # Analytics follow-up
        sa.Column(
            "baselines_recalculated",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Whether baselines were updated after sync",
        ),
        sa.Column(
            "patterns_detected",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Whether pattern detection ran after sync",
        ),
        sa.Column(
            "insights_generated",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Whether insights were regenerated after sync",
        ),
        # Context
        sa.Column(
            "trigger",
            sa.String(20),
            nullable=False,
            server_default="manual",
            comment="What triggered sync: scheduler, manual, webhook, startup",
        ),
        sa.Column(
            "priority",
            sa.String(20),
            nullable=True,
            comment="Sync priority: critical, high, normal, low",
        ),
        comment="Complete audit trail of every sync attempt",
    )

    # Composite indexes for common queries
    op.create_index(
        "ix_sync_logs_user_started",
        "sync_logs",
        ["user_id", "started_at"],
    )
    op.create_index(
        "ix_sync_logs_status_started",
        "sync_logs",
        ["status", "started_at"],
    )
    op.create_index(
        "ix_sync_logs_error_type_started",
        "sync_logs",
        ["error_type", "started_at"],
    )


def downgrade() -> None:
    """Drop sync_logs table and indexes."""
    op.drop_index("ix_sync_logs_error_type_started", table_name="sync_logs")
    op.drop_index("ix_sync_logs_status_started", table_name="sync_logs")
    op.drop_index("ix_sync_logs_user_started", table_name="sync_logs")
    op.drop_table("sync_logs")
