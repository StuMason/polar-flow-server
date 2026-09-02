"""Null physiologically-impossible zero HR aggregates from old syncs.

The continuous-HR transformer now excludes zero/no-signal samples before
computing min/avg/max, but rows synced before that fix still carry
hr_min = 0 (a dead person's resting heart rate). Heal them in place -
zero means "no valid samples", i.e. NULL.

Revision ID: h9i0j1k2l3m4
Revises: g8h9i0j1k2l3
Create Date: 2026-08-05 09:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h9i0j1k2l3m4"
down_revision: str | None = "g8h9i0j1k2l3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace zero HR aggregates with NULL."""
    op.execute("UPDATE continuous_heart_rate SET hr_min = NULL WHERE hr_min = 0")
    op.execute("UPDATE continuous_heart_rate SET hr_avg = NULL WHERE hr_avg = 0")
    op.execute("UPDATE continuous_heart_rate SET hr_max = NULL WHERE hr_max = 0")


def downgrade() -> None:
    """Irreversible data fix - zeros were noise, not data."""
