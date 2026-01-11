"""Sleep data transformer.

Converts polar-flow SDK SleepData model to database-ready dictionary.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polar_flow.models.sleep import SleepData


class SleepTransformer:
    """Transform SDK SleepData -> Database Sleep dict."""

    @staticmethod
    def transform(sdk_sleep: SleepData, user_id: str) -> dict[str, Any]:
        """Convert SDK sleep model to database-ready dict."""
        sleep_date = sdk_sleep.date
        if isinstance(sleep_date, str):
            sleep_date = date_type.fromisoformat(sleep_date)

        return {
            "date": sleep_date,
            "sleep_start_time": (
                sdk_sleep.sleep_start_time.isoformat() if sdk_sleep.sleep_start_time else None
            ),
            "sleep_end_time": (
                sdk_sleep.sleep_end_time.isoformat() if sdk_sleep.sleep_end_time else None
            ),
            "total_sleep_seconds": (
                sdk_sleep.light_sleep + sdk_sleep.deep_sleep + sdk_sleep.rem_sleep
            ),
            "light_sleep_seconds": sdk_sleep.light_sleep,
            "deep_sleep_seconds": sdk_sleep.deep_sleep,
            "rem_sleep_seconds": sdk_sleep.rem_sleep,
            "interruptions_seconds": sdk_sleep.total_interruption_duration,
            "sleep_score": sdk_sleep.sleep_score,
            "sleep_rating": sdk_sleep.sleep_rating,
        }
