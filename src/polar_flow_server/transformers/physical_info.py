"""Physical information transformer.

Converts polar-flow SDK UserPhysicalInfo model to database-ready dictionary.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polar_flow.models.physical_info import UserPhysicalInfo

_DURATION_PATTERN = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?")


def _duration_seconds(value: str | None) -> int | None:
    """Parse an ISO 8601 duration like PT8H to seconds."""
    if not value:
        return None
    match = _DURATION_PATTERN.match(value)
    if not match or not any(match.groups()):
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = float(match.group(3) or 0)
    return int(hours * 3600 + minutes * 60 + seconds)


class PhysicalInfoTransformer:
    """Transform SDK UserPhysicalInfo -> Database PhysicalInfo dict.

    recorded_at is Polar's modified timestamp (falling back to created, then
    the sync moment) so the (user_id, recorded_at) upsert stays idempotent
    across repeated syncs while real profile changes create new history rows.
    """

    @staticmethod
    def transform(sdk_info: UserPhysicalInfo, user_id: str) -> dict[str, Any]:
        """Convert SDK physical info model to database-ready dict."""
        recorded_at = sdk_info.modified or sdk_info.created or datetime.now(tz=UTC)

        return {
            "recorded_at": recorded_at,
            "weight_kg": sdk_info.weight,
            "height_cm": sdk_info.height,
            "birthday": sdk_info.birthday,
            "gender": sdk_info.gender,
            "maximum_heart_rate": sdk_info.maximum_heart_rate,
            "resting_heart_rate": sdk_info.resting_heart_rate,
            "aerobic_threshold": sdk_info.aerobic_threshold,
            "anaerobic_threshold": sdk_info.anaerobic_threshold,
            "vo2_max": sdk_info.vo2_max,
            "weight_source": sdk_info.weight_source,
            "training_background": sdk_info.training_background,
            "typical_day": sdk_info.typical_day,
            "sleep_goal_seconds": _duration_seconds(sdk_info.sleep_goal),
        }
