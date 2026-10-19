"""Add the unique constraints the biosensing upserts target (issue #144).

The body temperature, skin temperature, SpO2 and ECG syncs upsert with
ON CONFLICT on (user_id, start_time), (user_id, sleep_date) and
(user_id, test_time), but none of those tables ever had a matching
unique constraint. Postgres rejects every such INSERT, which aborts
the whole sync transaction, so these tables should be empty. Any
duplicates (hand-inserted rows) are removed first, keeping the newest,
so the constraint can never block startup. A table that already has a
unique constraint on the same columns, such as the workaround posted on
the issue, is left alone.

Revision ID: m4n5o6p7q8r9
Revises: l3m4n5o6p7q8
Create Date: 2026-10-19 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m4n5o6p7q8r9"
down_revision: str | None = "l3m4n5o6p7q8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINTS = [
    ("body_temperature", "uq_body_temperature_user_start_time", ["user_id", "start_time"]),
    ("skin_temperature", "uq_skin_temperature_user_sleep_date", ["user_id", "sleep_date"]),
    ("spo2", "uq_spo2_user_test_time", ["user_id", "test_time"]),
    ("ecg", "uq_ecg_user_test_time", ["user_id", "test_time"]),
]


def upgrade() -> None:
    """Dedupe, then create each unique constraint unless one already exists."""
    inspector = sa.inspect(op.get_bind())
    for table, name, columns in CONSTRAINTS:
        existing = {frozenset(uc["column_names"]) for uc in inspector.get_unique_constraints(table)}
        if frozenset(columns) in existing:
            continue
        match = " AND ".join(f"a.{c} = b.{c}" for c in columns)
        op.execute(f"DELETE FROM {table} a USING {table} b WHERE {match} AND a.id < b.id")
        op.create_unique_constraint(name, table, columns)


def downgrade() -> None:
    """Drop the unique constraints."""
    for table, name, _ in CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
