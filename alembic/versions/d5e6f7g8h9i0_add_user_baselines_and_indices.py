"""Add user_baselines table and analytics indices

Revision ID: d5e6f7g8h9i0
Revises: c4d5e6f7g8h9
Create Date: 2026-01-13

This migration adds:
1. user_baselines table for storing computed personal baselines
2. Composite indices on existing tables for efficient baseline calculations
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e6f7g8h9i0"
down_revision: str | Sequence[str] | None = "c4d5e6f7g8h9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create user_baselines table
    op.create_table(
        "user_baselines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("metric_name", sa.String(length=50), nullable=False),
        # Baseline values
        sa.Column("baseline_value", sa.Float(), nullable=False),
        sa.Column("baseline_7d", sa.Float(), nullable=True),
        sa.Column("baseline_30d", sa.Float(), nullable=True),
        sa.Column("baseline_90d", sa.Float(), nullable=True),
        # Statistics for anomaly detection
        sa.Column("std_dev", sa.Float(), nullable=True),
        sa.Column("median_value", sa.Float(), nullable=True),
        sa.Column("q1", sa.Float(), nullable=True),
        sa.Column("q3", sa.Float(), nullable=True),
        sa.Column("min_value", sa.Float(), nullable=True),
        sa.Column("max_value", sa.Float(), nullable=True),
        # Data quality
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="insufficient",
        ),
        # Data range
        sa.Column("data_start_date", sa.Date(), nullable=True),
        sa.Column("data_end_date", sa.Date(), nullable=True),
        # Calculation metadata
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        # Timestamps from TimestampMixin
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Constraints
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "metric_name", name="uq_user_baseline"),
        comment="User-specific baseline calculations for analytics",
    )

    # Indices for user_baselines
    op.create_index(
        op.f("ix_user_baselines_user_id"), "user_baselines", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_user_baselines_metric_name"),
        "user_baselines",
        ["metric_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_baselines_status"), "user_baselines", ["status"], unique=False
    )

    # Composite indices on existing tables for efficient baseline calculations
    # These support queries like: WHERE user_id = ? AND date >= ? ORDER BY date
    op.create_index(
        "idx_nightly_recharge_user_date",
        "nightly_recharge",
        ["user_id", "date"],
        unique=False,
    )
    op.create_index(
        "idx_sleep_user_date",
        "sleep",
        ["user_id", "date"],
        unique=False,
    )
    op.create_index(
        "idx_activity_user_date",
        "activity",
        ["user_id", "date"],
        unique=False,
    )
    op.create_index(
        "idx_cardio_load_user_date",
        "cardio_load",
        ["user_id", "date"],
        unique=False,
    )
    op.create_index(
        "idx_continuous_hr_user_date",
        "continuous_heart_rate",
        ["user_id", "date"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop composite indices from existing tables
    op.drop_index("idx_continuous_hr_user_date", table_name="continuous_heart_rate")
    op.drop_index("idx_cardio_load_user_date", table_name="cardio_load")
    op.drop_index("idx_activity_user_date", table_name="activity")
    op.drop_index("idx_sleep_user_date", table_name="sleep")
    op.drop_index("idx_nightly_recharge_user_date", table_name="nightly_recharge")

    # Drop user_baselines indices
    op.drop_index(op.f("ix_user_baselines_status"), table_name="user_baselines")
    op.drop_index(op.f("ix_user_baselines_metric_name"), table_name="user_baselines")
    op.drop_index(op.f("ix_user_baselines_user_id"), table_name="user_baselines")

    # Drop user_baselines table
    op.drop_table("user_baselines")
