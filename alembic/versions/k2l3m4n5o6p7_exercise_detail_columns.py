"""Add exercise detail columns: HR zones, samples, route (issue #76).

Fetched inline via the samples/zones/route query flags on the modern
hashed-ID exercise endpoint (SDK 1.5.0). Also captures running index
and the Training Load Pro breakdown, which the API always returned.

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
Create Date: 2026-08-05 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "k2l3m4n5o6p7"
down_revision: str | None = "j1k2l3m4n5o6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add exercise detail columns."""
    op.add_column("exercise", sa.Column("running_index", sa.Integer(), nullable=True))
    op.add_column("exercise", sa.Column("training_load_pro_json", sa.Text(), nullable=True))
    op.add_column("exercise", sa.Column("heart_rate_zones_json", sa.Text(), nullable=True))
    op.add_column("exercise", sa.Column("samples_json", sa.Text(), nullable=True))
    op.add_column("exercise", sa.Column("route_json", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop exercise detail columns."""
    for col in (
        "running_index",
        "training_load_pro_json",
        "heart_rate_zones_json",
        "samples_json",
        "route_json",
    ):
        op.drop_column("exercise", col)
