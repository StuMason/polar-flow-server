"""Temperature data transformers.

Converts polar-flow SDK temperature models to database-ready dictionaries.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polar_flow.models.biosensing import BodyTemperaturePeriod, SkinTemperature


class BodyTemperatureTransformer:
    """Transform SDK BodyTemperaturePeriod -> Database BodyTemperature dict.

    Maps SDK field names to database column names with proper type conversions.

    SDK Fields -> Database Fields:
    - source_device_id -> device_id
    - start_time -> start_time (ISO string to datetime)
    - end_time -> end_time (ISO string to datetime)
    - measurement_type -> measurement_type
    - sensor_location -> sensor_location
    - samples -> samples_json (serialized)
    - avg_temperature (computed) -> temp_avg
    - min_temperature (computed) -> temp_min
    - max_temperature (computed) -> temp_max
    """

    @staticmethod
    def transform(sdk_temp: BodyTemperaturePeriod, user_id: str) -> dict[str, Any]:
        """Convert SDK body temperature model to database-ready dict.

        Args:
            sdk_temp: SDK BodyTemperaturePeriod instance from polar-flow
            user_id: User identifier for database record

        Returns:
            Dict ready for database insertion with all fields mapped correctly
        """
        # Parse ISO datetime strings
        start_dt = datetime.fromisoformat(sdk_temp.start_time.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(sdk_temp.end_time.replace("Z", "+00:00"))

        # Serialize samples to JSON
        samples_json = None
        if sdk_temp.samples:
            samples_json = json.dumps(
                [
                    {
                        "temp_c": s.temperature_celsius,
                        "time_ms": s.recording_time_delta_milliseconds,
                    }
                    for s in sdk_temp.samples
                ]
            )

        return {
            "device_id": sdk_temp.source_device_id,
            "start_time": start_dt,
            "end_time": end_dt,
            "measurement_type": sdk_temp.measurement_type,
            "sensor_location": sdk_temp.sensor_location,
            "temp_min": sdk_temp.min_temperature,
            "temp_max": sdk_temp.max_temperature,
            "temp_avg": sdk_temp.avg_temperature,
            "sample_count": len(sdk_temp.samples) if sdk_temp.samples else 0,
            "samples_json": samples_json,
        }


class SkinTemperatureTransformer:
    """Transform SDK SkinTemperature -> Database SkinTemperature dict.

    Maps SDK field names to database column names with proper type conversions.

    SDK Fields -> Database Fields:
    - sleep_date -> sleep_date (string to date)
    - sleep_time_skin_temperature_celsius -> temperature_celsius
    - deviation_from_baseline_celsius -> deviation_from_baseline
    - is_elevated (computed) -> is_elevated
    """

    @staticmethod
    def transform(sdk_temp: SkinTemperature, user_id: str) -> dict[str, Any]:
        """Convert SDK skin temperature model to database-ready dict.

        Args:
            sdk_temp: SDK SkinTemperature instance from polar-flow
            user_id: User identifier for database record

        Returns:
            Dict ready for database insertion with all fields mapped correctly
        """
        from datetime import date as date_type

        # Parse date string
        sleep_date = date_type.fromisoformat(sdk_temp.sleep_date)

        return {
            "sleep_date": sleep_date,
            "temperature_celsius": sdk_temp.sleep_time_skin_temperature_celsius,
            "deviation_from_baseline": sdk_temp.deviation_from_baseline_celsius,
            "is_elevated": sdk_temp.is_elevated,
        }
