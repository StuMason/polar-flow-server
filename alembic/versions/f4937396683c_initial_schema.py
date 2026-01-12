"""Initial schema

This migration captures the initial database schema for polar-flow-server.
The schema was created via SQLAlchemy's create_all() before Alembic was set up,
so this migration is intentionally empty - it marks the baseline state.

All 16 tables are already present:
- users, app_settings (core)
- sleep, nightly_recharge, sleepwise_alertness, sleepwise_bedtime (sleep)
- activity, activity_samples (activity)
- exercise (exercise)
- continuous_heart_rate, cardio_load (heart rate)
- spo2, ecg, body_temperature, skin_temperature (biosensing)

Future migrations will modify this baseline schema.

Revision ID: f4937396683c
Revises:
Create Date: 2026-01-12 12:19:11.093395

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "f4937396683c"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    No-op: Initial schema already exists from create_all().
    This migration marks the baseline for future migrations.
    """
    pass


def downgrade() -> None:
    """Downgrade schema.

    No-op: Cannot downgrade from initial schema.
    To fully reset, drop all tables manually.
    """
    pass
