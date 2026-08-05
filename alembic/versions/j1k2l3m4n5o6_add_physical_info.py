"""Add physical_info snapshots table (issue #75).

VO2 max, HR thresholds, weight, and profile settings from the
non-transactional GET /v3/users/physical-info endpoint (AccessLink
13.01.2026). Keyed by (user_id, recorded_at) so profile changes build
a history while repeated syncs stay idempotent.

Revision ID: j1k2l3m4n5o6
Revises: i0j1k2l3m4n5
Create Date: 2026-08-05 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "j1k2l3m4n5o6"
down_revision: str | None = "i0j1k2l3m4n5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create physical_info table."""
    op.create_table(
        "physical_info",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False, index=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("height_cm", sa.Float(), nullable=True),
        sa.Column("birthday", sa.Date(), nullable=True),
        sa.Column("gender", sa.String(20), nullable=True),
        sa.Column("maximum_heart_rate", sa.Integer(), nullable=True),
        sa.Column("resting_heart_rate", sa.Integer(), nullable=True),
        sa.Column("aerobic_threshold", sa.Integer(), nullable=True),
        sa.Column("anaerobic_threshold", sa.Integer(), nullable=True),
        sa.Column("vo2_max", sa.Integer(), nullable=True),
        sa.Column("weight_source", sa.String(30), nullable=True),
        sa.Column("training_background", sa.String(30), nullable=True),
        sa.Column("typical_day", sa.String(30), nullable=True),
        sa.Column("sleep_goal_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("user_id", "recorded_at", name="uq_physical_info_user_recorded"),
        comment="Physical info snapshots (VO2 max, HR thresholds, weight)",
    )


def downgrade() -> None:
    """Drop physical_info table."""
    op.drop_table("physical_info")
