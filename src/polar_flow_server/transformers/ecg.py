"""ECG data transformer.

Converts polar-flow SDK ECGResult model to database-ready dictionary.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polar_flow.models.biosensing import ECGResult  # type: ignore[import-not-found]


class ECGTransformer:
    """Transform SDK ECGResult -> Database ECG dict.

    Maps SDK field names to database column names with proper type conversions.
    Serializes waveform samples to JSON for storage.

    SDK Fields -> Database Fields:
    - source_device_id -> device_id
    - test_time -> test_time (unix ms to datetime)
    - time_zone_offset -> timezone_offset_minutes
    - average_heart_rate_bpm -> avg_heart_rate
    - heart_rate_variability_ms -> hrv_ms
    - heart_rate_variability_level -> hrv_level
    - rri_ms -> rri_ms
    - pulse_transit_time_systolic_ms -> ptt_systolic_ms
    - pulse_transit_time_diastolic_ms -> ptt_diastolic_ms
    - pulse_transit_time_quality_index -> ptt_quality_index
    - samples -> samples_json (serialized)
    - quality_measurements -> quality_json (serialized)
    - duration_seconds -> duration_seconds (computed)
    """

    @staticmethod
    def transform(sdk_ecg: ECGResult, user_id: str) -> dict[str, Any]:
        """Convert SDK ECG model to database-ready dict.

        Args:
            sdk_ecg: SDK ECGResult instance from polar-flow
            user_id: User identifier for database record

        Returns:
            Dict ready for database insertion with all fields mapped correctly
        """
        # Convert unix timestamp (ms) to datetime
        test_datetime = datetime.fromtimestamp(sdk_ecg.test_time / 1000, tz=UTC)

        # Serialize samples to JSON
        samples_json = None
        if sdk_ecg.samples:
            samples_json = json.dumps(
                [
                    {
                        "time_ms": s.recording_time_delta_ms,
                        "amplitude_mv": s.amplitude_mv,
                    }
                    for s in sdk_ecg.samples
                ]
            )

        # Serialize quality measurements to JSON
        quality_json = None
        if sdk_ecg.quality_measurements:
            quality_json = json.dumps(
                [
                    {
                        "time_ms": q.recording_time_delta_ms,
                        "quality": q.quality_level,
                    }
                    for q in sdk_ecg.quality_measurements
                ]
            )

        return {
            "device_id": sdk_ecg.source_device_id,
            "test_time": test_datetime,
            "timezone_offset_minutes": sdk_ecg.time_zone_offset,
            "avg_heart_rate": sdk_ecg.average_heart_rate_bpm,
            "hrv_ms": sdk_ecg.heart_rate_variability_ms,
            "hrv_level": sdk_ecg.heart_rate_variability_level,
            "rri_ms": sdk_ecg.rri_ms,
            "ptt_systolic_ms": sdk_ecg.pulse_transit_time_systolic_ms,
            "ptt_diastolic_ms": sdk_ecg.pulse_transit_time_diastolic_ms,
            "ptt_quality_index": sdk_ecg.pulse_transit_time_quality_index,
            "sample_count": len(sdk_ecg.samples) if sdk_ecg.samples else 0,
            "samples_json": samples_json,
            "quality_json": quality_json,
            "duration_seconds": sdk_ecg.duration_seconds,
        }
