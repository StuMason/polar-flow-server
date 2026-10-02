"""Heal -1 sentinels, fill training load and sleep HRV on existing rows.

The transformers now store Polar's -1 "not available" sentinel as NULL,
fall back to Training Load Pro cardio load when an exercise has no
training_load, and the recharge sync copies HRV and breathing rate onto
the matching sleep row. Apply the same rules to rows synced before that.

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7
Create Date: 2026-10-02 11:00:00.000000

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "l3m4n5o6p7q8"
down_revision: str | None = "k2l3m4n5o6p7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Null sentinels, backfill exercise training load and sleep HRV."""
    op.execute("UPDATE cardio_load SET cardio_load = NULL WHERE cardio_load < 0")
    op.execute("UPDATE cardio_load SET cardio_load_ratio = NULL WHERE cardio_load_ratio < 0")
    op.execute("UPDATE cardio_load SET tolerance = NULL WHERE tolerance < 0")

    op.execute(
        """
        UPDATE sleep AS s
        SET hrv_avg = r.hrv_avg, breathing_rate_avg = r.breathing_rate_avg
        FROM nightly_recharge AS r
        WHERE s.user_id = r.user_id AND s.date = r.date
        """
    )

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, training_load, training_load_pro_json FROM exercise "
            "WHERE training_load_pro_json IS NOT NULL"
        )
    ).fetchall()
    for row in rows:
        tlp = json.loads(row.training_load_pro_json)
        cleaned = {
            key: None if isinstance(value, (int, float)) and value < 0 else value
            for key, value in tlp.items()
        }
        training_load = row.training_load
        cardio_load = cleaned.get("cardio-load")
        if training_load is None and isinstance(cardio_load, (int, float)):
            training_load = float(cardio_load)
        conn.execute(
            sa.text(
                "UPDATE exercise SET training_load = :training_load, "
                "training_load_pro_json = :tlp WHERE id = :id"
            ),
            {"training_load": training_load, "tlp": json.dumps(cleaned), "id": row.id},
        )


def downgrade() -> None:
    """Irreversible data fix - sentinels were never data."""
