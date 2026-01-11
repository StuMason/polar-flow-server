"""SleepWise Alertness data transformer.

Converts polar-flow SDK SleepWiseAlertness model to database-ready dictionary.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polar_flow.models.sleepwise_alertness import SleepWiseAlertness


class SleepWiseAlertnessTransformer:
    """Transform SDK SleepWiseAlertness -> Database SleepWiseAlertness dict.

    Maps SDK field names to database column names with proper type conversions.

    SDK Fields -> Database Fields:
    - grade -> grade
    - grade_validity_seconds -> grade_validity_seconds
    - grade_type -> grade_type
    - grade_classification -> grade_classification
    - validity -> validity
    - sleep_inertia -> sleep_inertia
    - sleep_type -> sleep_type
    - result_type -> result_type
    - period_start_time -> period_start_time (str to datetime)
    - period_end_time -> period_end_time (str to datetime)
    - sleep_period_start_time -> sleep_period_start_time (str to datetime)
    - sleep_period_end_time -> sleep_period_end_time (str to datetime)
    - sleep_timezone_offset_minutes -> sleep_timezone_offset_minutes
    - hourly_data -> hourly_data_json (list to JSON string)
    """

    @staticmethod
    def transform(sdk_alertness: SleepWiseAlertness, user_id: str) -> dict[str, Any]:
        """Convert SDK alertness model to database-ready dict.

        Args:
            sdk_alertness: SDK SleepWiseAlertness instance from polar-flow
            user_id: User identifier for database record

        Returns:
            Dict ready for database insertion with all fields mapped correctly
        """
        # Parse datetime strings
        period_start = datetime.fromisoformat(sdk_alertness.period_start_time)
        period_end = datetime.fromisoformat(sdk_alertness.period_end_time)
        sleep_start = datetime.fromisoformat(sdk_alertness.sleep_period_start_time)
        sleep_end = datetime.fromisoformat(sdk_alertness.sleep_period_end_time)

        # Convert hourly data to JSON
        hourly_json = None
        if sdk_alertness.hourly_data:
            hourly_json = json.dumps(
                [
                    {
                        "validity": h.validity,
                        "alertness_level": h.alertness_level,
                        "start_time": h.start_time,
                        "end_time": h.end_time,
                    }
                    for h in sdk_alertness.hourly_data
                ]
            )

        return {
            "grade": sdk_alertness.grade,
            "grade_validity_seconds": sdk_alertness.grade_validity_seconds,
            "grade_type": sdk_alertness.grade_type,
            "grade_classification": sdk_alertness.grade_classification,
            "validity": sdk_alertness.validity,
            "sleep_inertia": sdk_alertness.sleep_inertia,
            "sleep_type": sdk_alertness.sleep_type,
            "result_type": sdk_alertness.result_type,
            "period_start_time": period_start,
            "period_end_time": period_end,
            "sleep_period_start_time": sleep_start,
            "sleep_period_end_time": sleep_end,
            "sleep_timezone_offset_minutes": sdk_alertness.sleep_timezone_offset_minutes,
            "hourly_data_json": hourly_json,
        }
