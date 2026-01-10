"""Activity data transformer.

Converts polar-flow SDK ActivitySummary model to database-ready dictionary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polar_flow.models.activity import ActivitySummary


class ActivityTransformer:
    """Transform SDK ActivitySummary -> Database Activity dict.

    Maps SDK field names to database column names with proper type conversions.

    SDK Fields -> Database Fields:
    - start_time.date() -> date (extract date from datetime)
    - steps -> steps
    - distance_from_steps -> distance_meters
    - active_calories -> calories_active
    - calories -> calories_total
    - active_duration_seconds -> active_time_seconds (computed property)
    - daily_activity -> activity_score (cast to int)
    - inactivity_alert_count -> inactivity_alerts
    """

    @staticmethod
    def transform(sdk_activity: ActivitySummary, user_id: str) -> dict[str, Any]:
        """Convert SDK activity model to database-ready dict.

        Args:
            sdk_activity: SDK ActivitySummary instance from polar-flow
            user_id: User identifier for database record

        Returns:
            Dict ready for database insertion with all fields mapped correctly
        """
        return {
            "date": sdk_activity.start_time.date(),
            "steps": sdk_activity.steps,
            "distance_meters": sdk_activity.distance_from_steps,
            "calories_active": sdk_activity.active_calories,
            "calories_total": sdk_activity.calories,
            # active_duration_seconds is a computed property on the SDK model
            "active_time_seconds": sdk_activity.active_duration_seconds,
            # daily_activity is a float, database expects int
            "activity_score": int(sdk_activity.daily_activity),
            "inactivity_alerts": sdk_activity.inactivity_alert_count,
        }
