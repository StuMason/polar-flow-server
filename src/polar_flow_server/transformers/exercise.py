"""Exercise data transformer.

Converts polar-flow SDK ExerciseDetails model to database-ready dictionary.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polar_flow.models.exercise import ExerciseDetails


class ExerciseTransformer:
    """Transform SDK ExerciseDetails -> Database Exercise dict.

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
    def transform(sdk_exercise: ExerciseDetails, user_id: str) -> dict[str, Any]:
        """Convert SDK exercise model to database-ready dict.

        Args:
            sdk_exercise: SDK ExerciseDetails instance from polar-flow
            user_id: User identifier for database record

        Returns:
            Dict ready for database insertion with all fields mapped correctly
        """
        # Calculate stop_time from start_time + duration
        stop_time = sdk_exercise.start_time + timedelta(seconds=sdk_exercise.duration_seconds)

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
            "training_load": sdk_exercise.training_load,
            "has_route": sdk_exercise.has_route,
        }
