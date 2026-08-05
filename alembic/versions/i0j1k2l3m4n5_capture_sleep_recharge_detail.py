"""Capture rich sleep & recharge fields the API returns (issue #77).

Sleep gains device/structure scalars (continuity, cycles, sleep charge,
goal, group scores, interruption split) plus the overnight hypnogram and
heart-rate sample series as JSON. Nightly recharge gains the overall
recovery status, beat-to-beat average and the 5-minute HRV/breathing
series as JSON.

Revision ID: i0j1k2l3m4n5
Revises: h9i0j1k2l3m4
Create Date: 2026-08-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "i0j1k2l3m4n5"
down_revision: str | None = "h9i0j1k2l3m4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add sleep & recharge detail columns."""
    op.add_column("sleep", sa.Column("device_id", sa.String(50), nullable=True))
    op.add_column("sleep", sa.Column("continuity", sa.Float(), nullable=True))
    op.add_column("sleep", sa.Column("continuity_class", sa.Integer(), nullable=True))
    op.add_column("sleep", sa.Column("sleep_cycles", sa.Integer(), nullable=True))
    op.add_column("sleep", sa.Column("unrecognized_sleep_seconds", sa.Integer(), nullable=True))
    op.add_column("sleep", sa.Column("short_interruption_seconds", sa.Integer(), nullable=True))
    op.add_column("sleep", sa.Column("long_interruption_seconds", sa.Integer(), nullable=True))
    op.add_column("sleep", sa.Column("sleep_charge", sa.Integer(), nullable=True))
    op.add_column("sleep", sa.Column("sleep_goal_seconds", sa.Integer(), nullable=True))
    op.add_column("sleep", sa.Column("group_duration_score", sa.Float(), nullable=True))
    op.add_column("sleep", sa.Column("group_solidity_score", sa.Float(), nullable=True))
    op.add_column("sleep", sa.Column("group_regeneration_score", sa.Float(), nullable=True))
    op.add_column("sleep", sa.Column("hypnogram_json", sa.Text(), nullable=True))
    op.add_column("sleep", sa.Column("heart_rate_samples_json", sa.Text(), nullable=True))

    op.add_column(
        "nightly_recharge", sa.Column("nightly_recharge_status", sa.Integer(), nullable=True)
    )
    op.add_column("nightly_recharge", sa.Column("beat_to_beat_avg", sa.Integer(), nullable=True))
    op.add_column("nightly_recharge", sa.Column("hrv_samples_json", sa.Text(), nullable=True))
    op.add_column("nightly_recharge", sa.Column("breathing_samples_json", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop sleep & recharge detail columns."""
    for col in (
        "device_id",
        "continuity",
        "continuity_class",
        "sleep_cycles",
        "unrecognized_sleep_seconds",
        "short_interruption_seconds",
        "long_interruption_seconds",
        "sleep_charge",
        "sleep_goal_seconds",
        "group_duration_score",
        "group_solidity_score",
        "group_regeneration_score",
        "hypnogram_json",
        "heart_rate_samples_json",
    ):
        op.drop_column("sleep", col)

    for col in (
        "nightly_recharge_status",
        "beat_to_beat_avg",
        "hrv_samples_json",
        "breathing_samples_json",
    ):
        op.drop_column("nightly_recharge", col)
