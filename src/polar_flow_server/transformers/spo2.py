"""SpO2 data transformer.

Converts polar-flow SDK SpO2Result model to database-ready dictionary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polar_flow.models.biosensing import SpO2Result  # type: ignore[import-not-found]


class SpO2Transformer:
    """Transform SDK SpO2Result -> Database SpO2 dict.

    Maps SDK field names to database column names with proper type conversions.

    SDK Fields -> Database Fields:
    - source_device_id -> device_id
    - test_time -> test_time (unix ms to datetime)
    - time_zone_offset -> timezone_offset_minutes
    - blood_oxygen_percent -> blood_oxygen_percent
    - spo2_class -> spo2_class
    - spo2_value_deviation_from_baseline -> spo2_deviation
    - spo2_quality_average_percent -> quality_percent
    - average_heart_rate_bpm -> avg_heart_rate
    - heart_rate_variability_ms -> hrv_ms
    - spo2_hrv_deviation_from_baseline -> hrv_deviation
    - altitude_meters -> altitude_meters
    - test_status -> test_status
    """

    @staticmethod
    def transform(sdk_spo2: SpO2Result, user_id: str) -> dict[str, Any]:
        """Convert SDK SpO2 model to database-ready dict.

        Args:
            sdk_spo2: SDK SpO2Result instance from polar-flow
            user_id: User identifier for database record

        Returns:
            Dict ready for database insertion with all fields mapped correctly
        """
        # Convert unix timestamp (ms) to datetime
        test_datetime = datetime.fromtimestamp(sdk_spo2.test_time / 1000, tz=UTC)

        return {
            "device_id": sdk_spo2.source_device_id,
            "test_time": test_datetime,
            "timezone_offset_minutes": sdk_spo2.time_zone_offset,
            "blood_oxygen_percent": sdk_spo2.blood_oxygen_percent,
            "spo2_class": sdk_spo2.spo2_class,
            "spo2_deviation": sdk_spo2.spo2_value_deviation_from_baseline,
            "quality_percent": sdk_spo2.spo2_quality_average_percent,
            "avg_heart_rate": sdk_spo2.average_heart_rate_bpm,
            "hrv_ms": sdk_spo2.heart_rate_variability_ms,
            "hrv_deviation": sdk_spo2.spo2_hrv_deviation_from_baseline,
            "altitude_meters": sdk_spo2.altitude_meters,
            "test_status": sdk_spo2.test_status,
        }
