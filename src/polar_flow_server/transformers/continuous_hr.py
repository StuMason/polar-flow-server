"""Continuous Heart Rate data transformer.

Converts polar-flow SDK ContinuousHeartRate model to database-ready dictionary.
"""

from __future__ import annotations

import json
from datetime import date as date_type
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polar_flow.models.continuous_hr import ContinuousHeartRate


class ContinuousHRTransformer:
    """Transform SDK ContinuousHeartRate -> Database ContinuousHeartRate dict.

    Maps SDK field names to database column names with proper type conversions.
    Computes min/max/avg for quick dashboard display.

    SDK Fields -> Database Fields:
    - date -> date (str to date)
    - len(heart_rate_samples) -> sample_count
    - computed min(heart_rate) -> hr_min
    - computed max(heart_rate) -> hr_max
    - computed avg(heart_rate) -> hr_avg
    - heart_rate_samples -> samples_json (list to JSON string)
    """

    @staticmethod
    def transform(sdk_hr: ContinuousHeartRate, user_id: str) -> dict[str, Any]:
        """Convert SDK continuous HR model to database-ready dict.

        Args:
            sdk_hr: SDK ContinuousHeartRate instance from polar-flow
            user_id: User identifier for database record

        Returns:
            Dict ready for database insertion with all fields mapped correctly
        """
        # Parse date from string if needed
        raw_date = sdk_hr.date
        hr_date: date_type = (
            date_type.fromisoformat(raw_date) if isinstance(raw_date, str) else raw_date
        )

        samples = sdk_hr.heart_rate_samples
        sample_count = len(samples)

        # Compute aggregates
        hr_min = None
        hr_max = None
        hr_avg = None

        if samples:
            hr_values = [s.heart_rate for s in samples]
            hr_min = min(hr_values)
            hr_max = max(hr_values)
            hr_avg = round(sum(hr_values) / len(hr_values))

        # Convert samples to JSON
        samples_json = None
        if samples:
            samples_json = json.dumps(
                [{"heart_rate": s.heart_rate, "sample_time": s.sample_time} for s in samples]
            )

        return {
            "date": hr_date,
            "sample_count": sample_count,
            "hr_min": hr_min,
            "hr_max": hr_max,
            "hr_avg": hr_avg,
            "samples_json": samples_json,
        }
