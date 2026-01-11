"""SleepWise Bedtime data transformer.

Converts polar-flow SDK SleepWiseBedtime model to database-ready dictionary.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polar_flow.models.sleepwise_bedtime import SleepWiseBedtime


class SleepWiseBedtimeTransformer:
    """Transform SDK SleepWiseBedtime -> Database SleepWiseBedtime dict.

    Maps SDK field names to database column names with proper type conversions.

    SDK Fields -> Database Fields:
    - validity -> validity
    - quality -> quality
    - result_type -> result_type
    - period_start_time -> period_start_time (str to datetime)
    - period_end_time -> period_end_time (str to datetime)
    - preferred_sleep_period_start_time -> preferred_sleep_start (str to datetime)
    - preferred_sleep_period_end_time -> preferred_sleep_end (str to datetime)
    - sleep_gate_start_time -> sleep_gate_start (str to datetime)
    - sleep_gate_end_time -> sleep_gate_end (str to datetime)
    - sleep_timezone_offset_minutes -> sleep_timezone_offset_minutes
    """

    @staticmethod
    def transform(sdk_bedtime: SleepWiseBedtime, user_id: str) -> dict[str, Any]:
        """Convert SDK bedtime model to database-ready dict.

        Args:
            sdk_bedtime: SDK SleepWiseBedtime instance from polar-flow
            user_id: User identifier for database record

        Returns:
            Dict ready for database insertion with all fields mapped correctly
        """
        # Parse datetime strings
        period_start = datetime.fromisoformat(sdk_bedtime.period_start_time)
        period_end = datetime.fromisoformat(sdk_bedtime.period_end_time)
        pref_start = datetime.fromisoformat(sdk_bedtime.preferred_sleep_period_start_time)
        pref_end = datetime.fromisoformat(sdk_bedtime.preferred_sleep_period_end_time)
        gate_start = datetime.fromisoformat(sdk_bedtime.sleep_gate_start_time)
        gate_end = datetime.fromisoformat(sdk_bedtime.sleep_gate_end_time)

        return {
            "validity": sdk_bedtime.validity,
            "quality": sdk_bedtime.quality,
            "result_type": sdk_bedtime.result_type,
            "period_start_time": period_start,
            "period_end_time": period_end,
            "preferred_sleep_start": pref_start,
            "preferred_sleep_end": pref_end,
            "sleep_gate_start": gate_start,
            "sleep_gate_end": gate_end,
            "sleep_timezone_offset_minutes": sdk_bedtime.sleep_timezone_offset_minutes,
        }
