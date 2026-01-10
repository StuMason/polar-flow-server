"""Activity Samples data transformer.

Converts polar-flow SDK DailyActivitySamples model to database-ready dictionary.
"""

from __future__ import annotations

import json
from datetime import date as date_type
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polar_flow.models.activity_samples import DailyActivitySamples


class ActivitySamplesTransformer:
    """Transform SDK DailyActivitySamples -> Database ActivitySamples dict.

    Maps SDK field names to database column names with proper type conversions.

    SDK Fields -> Database Fields:
    - date -> date (str to date)
    - steps.total_steps -> total_steps
    - steps.interval_ms -> interval_ms
    - len(steps.samples) -> sample_count
    - steps.samples -> samples_json (list to JSON string)
    """

    @staticmethod
    def transform(sdk_samples: DailyActivitySamples, user_id: str) -> dict[str, Any]:
        """Convert SDK activity samples model to database-ready dict.

        Args:
            sdk_samples: SDK DailyActivitySamples instance from polar-flow
            user_id: User identifier for database record

        Returns:
            Dict ready for database insertion with all fields mapped correctly
        """
        # Parse date from string if needed
        sample_date = sdk_samples.date
        if isinstance(sample_date, str):
            sample_date = date_type.fromisoformat(sample_date)

        # Extract step data
        step_data = sdk_samples.steps
        sample_count = len(step_data.samples)

        # Convert samples to JSON
        samples_json = None
        if step_data.samples:
            samples_json = json.dumps(
                [{"steps": s.steps, "timestamp": s.timestamp} for s in step_data.samples]
            )

        return {
            "date": sample_date,
            "total_steps": step_data.total_steps,
            "interval_ms": step_data.interval_ms,
            "sample_count": sample_count,
            "samples_json": samples_json,
        }
