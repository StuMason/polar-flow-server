"""Exercise data transformer.

Converts polar-flow SDK Exercise model to database-ready dictionary.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polar_flow.models.exercise import Exercise


def _clean_training_load_pro(
    training_load_pro: dict[str, float | str] | None,
) -> dict[str, float | str | None] | None:
    """Null Polar's -1 "not available" sentinel in Training Load Pro values."""
    if not training_load_pro:
        return None
    return {
        key: None if isinstance(value, (int, float)) and value < 0 else value
        for key, value in training_load_pro.items()
    }


def _training_load(
    training_load: float | None, training_load_pro: dict[str, float | str | None] | None
) -> float | None:
    """Polar's training_load, or Training Load Pro cardio load when that's all the watch sends."""
    if training_load is not None:
        return training_load
    cardio_load = (training_load_pro or {}).get("cardio-load")
    return float(cardio_load) if isinstance(cardio_load, (int, float)) else None


class ExerciseTransformer:
    """Transform SDK Exercise -> Database Exercise dict.

    Maps SDK field names to database column names with proper type conversions.

    SDK Fields -> Database Fields:
    - id -> polar_exercise_id
    - start_time -> start_time
    - start_time + duration_seconds -> stop_time (CALCULATED)
    - duration_seconds -> duration_seconds
    - sport -> sport
    - detailed_sport_info -> detailed_sport_info
    - distance -> distance_meters
    - average_heart_rate -> average_heart_rate (computed property)
    - maximum_heart_rate -> max_heart_rate (computed property, RENAMED)
    - calories -> calories
    - training_load -> training_load
    - has_route -> has_route
    """

    @staticmethod
    def transform(sdk_exercise: Exercise, user_id: str) -> dict[str, Any]:
        """Convert SDK exercise model to database-ready dict.

        Args:
            sdk_exercise: SDK Exercise instance from polar-flow
            user_id: User identifier for database record

        Returns:
            Dict ready for database insertion with all fields mapped correctly
        """
        # Calculate stop_time from start_time + duration
        stop_time = sdk_exercise.start_time + timedelta(seconds=sdk_exercise.duration_seconds)

        training_load_pro = _clean_training_load_pro(sdk_exercise.training_load_pro)
        zones = getattr(sdk_exercise, "heart_rate_zones", None)
        samples = getattr(sdk_exercise, "samples", None)
        route = getattr(sdk_exercise, "route", None)

        return {
            "polar_exercise_id": sdk_exercise.id,
            "start_time": sdk_exercise.start_time,
            "stop_time": stop_time,
            "duration_seconds": sdk_exercise.duration_seconds,
            "sport": sdk_exercise.sport,
            "detailed_sport_info": sdk_exercise.detailed_sport_info,
            "distance_meters": sdk_exercise.distance,
            # average_heart_rate and maximum_heart_rate are computed properties
            "average_heart_rate": sdk_exercise.average_heart_rate,
            "max_heart_rate": sdk_exercise.maximum_heart_rate,
            "calories": sdk_exercise.calories,
            "training_load": _training_load(sdk_exercise.training_load, training_load_pro),
            "has_route": sdk_exercise.has_route,
            "running_index": getattr(sdk_exercise, "running_index", None),
            "training_load_pro_json": json.dumps(training_load_pro) if training_load_pro else None,
            "heart_rate_zones_json": (
                json.dumps(
                    [
                        {
                            "index": z.index,
                            "lower_limit_bpm": z.lower_limit,
                            "upper_limit_bpm": z.upper_limit,
                            "in_zone_seconds": z.in_zone_seconds,
                        }
                        for z in zones
                    ]
                )
                if zones
                else None
            ),
            "samples_json": (
                json.dumps(
                    [
                        {
                            "sample_type": s.sample_type,
                            "recording_rate": s.recording_rate,
                            "values": s.values,
                        }
                        for s in samples
                    ]
                )
                if samples
                else None
            ),
            "route_json": (
                json.dumps(
                    [
                        {
                            "latitude": p.latitude,
                            "longitude": p.longitude,
                            "time": p.time,
                            "satellites": p.satellites,
                            "fix": p.fix,
                        }
                        for p in route
                    ]
                )
                if route
                else None
            ),
        }
