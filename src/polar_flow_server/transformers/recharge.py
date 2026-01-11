"""Recharge data transformer.

Converts polar-flow SDK NightlyRecharge model to database-ready dictionary.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polar_flow.models.recharge import NightlyRecharge


class RechargeTransformer:
    """Transform SDK NightlyRecharge -> Database NightlyRecharge dict.

    Maps SDK field names to database column names with proper type conversions.

    SDK Fields -> Database Fields:
    - date -> date (ensure date type)
    - ans_charge -> ans_charge
    - ans_charge_status -> ans_charge_status
    - heart_rate_variability_avg -> hrv_avg (RENAMED!)
    - breathing_rate_avg -> breathing_rate_avg
    - heart_rate_avg -> heart_rate_avg

    Note: SDK doesn't provide these database fields:
    - hrv_status, breathing_rate_status, heart_rate_status
    - sleep_score, sleep_charge, sleep_charge_status
    """

    @staticmethod
    def transform(sdk_recharge: NightlyRecharge, user_id: str) -> dict[str, Any]:
        """Convert SDK recharge model to database-ready dict.

        Args:
            sdk_recharge: SDK NightlyRecharge instance from polar-flow
            user_id: User identifier for database record

        Returns:
            Dict ready for database insertion with all fields mapped correctly
        """
        # Handle date - could be date object or string
        raw_date = sdk_recharge.date
        recharge_date: date_type = (
            date_type.fromisoformat(raw_date) if isinstance(raw_date, str) else raw_date
        )

        return {
            "date": recharge_date,
            "ans_charge": sdk_recharge.ans_charge,
            "ans_charge_status": sdk_recharge.ans_charge_status,
            # SDK field name differs from database column name
            "hrv_avg": sdk_recharge.heart_rate_variability_avg,
            "breathing_rate_avg": sdk_recharge.breathing_rate_avg,
            "heart_rate_avg": sdk_recharge.heart_rate_avg,
            # SDK doesn't provide status fields or sleep metrics
            # Database columns hrv_status, breathing_rate_status, heart_rate_status,
            # sleep_score, sleep_charge, sleep_charge_status remain null
        }
