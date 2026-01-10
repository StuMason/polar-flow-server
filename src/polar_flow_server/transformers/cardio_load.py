"""Cardio Load data transformer.

Converts polar-flow SDK CardioLoad model to database-ready dictionary.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polar_flow.models.cardio_load import CardioLoad


class CardioLoadTransformer:
    """Transform SDK CardioLoad -> Database CardioLoad dict.

    Maps SDK field names to database column names with proper type conversions.

    SDK Fields -> Database Fields:
    - date -> date (str to date)
    - cardio_load -> cardio_load
    - cardio_load_status -> cardio_load_status
    - cardio_load_ratio -> cardio_load_ratio
    - strain -> strain
    - tolerance -> tolerance
    - cardio_load_level.very_low -> load_very_low
    - cardio_load_level.low -> load_low
    - cardio_load_level.medium -> load_medium
    - cardio_load_level.high -> load_high
    - cardio_load_level.very_high -> load_very_high
    """

    @staticmethod
    def transform(sdk_cardio_load: CardioLoad, user_id: str) -> dict[str, Any]:
        """Convert SDK cardio load model to database-ready dict.

        Args:
            sdk_cardio_load: SDK CardioLoad instance from polar-flow
            user_id: User identifier for database record

        Returns:
            Dict ready for database insertion with all fields mapped correctly
        """
        # Parse date from string if needed
        load_date = sdk_cardio_load.date
        if isinstance(load_date, str):
            load_date = date_type.fromisoformat(load_date)

        # Extract load level distribution
        load_level = sdk_cardio_load.cardio_load_level

        return {
            "date": load_date,
            "cardio_load": sdk_cardio_load.cardio_load,
            "cardio_load_status": sdk_cardio_load.cardio_load_status,
            "cardio_load_ratio": sdk_cardio_load.cardio_load_ratio,
            "strain": sdk_cardio_load.strain,
            "tolerance": sdk_cardio_load.tolerance,
            "load_very_low": load_level.very_low,
            "load_low": load_level.low,
            "load_medium": load_level.medium,
            "load_high": load_level.high,
            "load_very_high": load_level.very_high,
        }
