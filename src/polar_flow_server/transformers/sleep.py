"""Sleep data transformer.

Converts polar-flow SDK SleepData model to database-ready dictionary.
"""

from __future__ import annotations

import json
from datetime import date as date_type
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polar_flow.models.sleep import SleepData


class SleepTransformer:
    """Transform SDK SleepData -> Database Sleep dict.

    Polar uses in-band sentinels for "no data" (continuity 0, sleep_charge -1,
    heart rate 0); those are stored as NULL so aggregates and baselines never
    ingest them as real values.
    """

    @staticmethod
    def transform(sdk_sleep: SleepData, user_id: str) -> dict[str, Any]:
        """Convert SDK sleep model to database-ready dict."""
        sleep_date = sdk_sleep.date
        if isinstance(sleep_date, str):
            sleep_date = date_type.fromisoformat(sleep_date)

        # Overnight HR aggregates from the ~5-minute sample series.
        # Zero-bpm samples mean "no signal", never a real heart rate.
        hr_values = [v for v in (sdk_sleep.heart_rate_samples or {}).values() if v > 0]

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
            # Device & sleep structure
            "device_id": sdk_sleep.device_id or None,
            # Polar sends 0 / class 0 when continuity wasn't measured
            "continuity": sdk_sleep.continuity if sdk_sleep.continuity > 0 else None,
            "continuity_class": (
                sdk_sleep.continuity_class if sdk_sleep.continuity_class > 0 else None
            ),
            "sleep_cycles": sdk_sleep.sleep_cycles,
            "unrecognized_sleep_seconds": sdk_sleep.unrecognized_sleep_stage,
            "short_interruption_seconds": sdk_sleep.short_interruption_duration,
            "long_interruption_seconds": sdk_sleep.long_interruption_duration,
            # Polar sends -1 when sleep charge is unavailable
            "sleep_charge": (
                sdk_sleep.sleep_charge
                if sdk_sleep.sleep_charge is not None and sdk_sleep.sleep_charge > 0
                else None
            ),
            "sleep_goal_seconds": sdk_sleep.sleep_goal,
            "group_duration_score": sdk_sleep.group_duration_score,
            "group_solidity_score": sdk_sleep.group_solidity_score,
            "group_regeneration_score": sdk_sleep.group_regeneration_score,
            # Overnight series
            "hypnogram_json": (json.dumps(sdk_sleep.hypnogram) if sdk_sleep.hypnogram else None),
            "heart_rate_samples_json": (
                json.dumps(sdk_sleep.heart_rate_samples) if sdk_sleep.heart_rate_samples else None
            ),
            # In-sleep HR aggregates derived from the sample series
            "heart_rate_avg": round(sum(hr_values) / len(hr_values), 1) if hr_values else None,
            "heart_rate_min": min(hr_values) if hr_values else None,
            "heart_rate_max": max(hr_values) if hr_values else None,
        }
