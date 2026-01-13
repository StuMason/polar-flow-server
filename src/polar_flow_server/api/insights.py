"""Unified insights API endpoints."""

import re
from typing import Any

from litestar import Router, get
from litestar.exceptions import ValidationException
from litestar.status_codes import HTTP_200_OK
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.core.auth import per_user_api_key_guard
from polar_flow_server.services.insights import InsightsService

# Regex for valid user_id format (alphanumeric, underscores, hyphens)
USER_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def validate_user_id(user_id: str) -> str:
    """Validate user_id format to prevent injection attacks.

    Args:
        user_id: The user identifier to validate

    Returns:
        The validated user_id

    Raises:
        ValidationException: If user_id format is invalid
    """
    if not user_id or len(user_id) > 100:
        raise ValidationException("Invalid user_id: must be 1-100 characters")
    if not USER_ID_PATTERN.match(user_id):
        raise ValidationException("Invalid user_id: must be alphanumeric with _ or - only")
    return user_id


@get("/users/{user_id:str}/insights", status_code=HTTP_200_OK)
async def get_insights(
    user_id: str,
    session: AsyncSession,
) -> dict[str, Any]:
    """Get unified insights for a user.

    Returns a comprehensive insights package including:
    - Current metric values
    - Personal baseline comparisons
    - Detected patterns (correlations, trends, risk scores)
    - Anomalies (values outside normal bounds)
    - Natural language observations for coaching
    - Actionable suggestions

    The response includes feature availability based on data history.
    Features unlock progressively as more data becomes available:
    - 7 days: Basic 7-day baselines
    - 21 days: Pattern detection, anomaly detection
    - 30 days: Full 30-day baselines
    - 60 days: ML predictions (when implemented)

    Example response structure:
    ```json
    {
      "user_id": "12345",
      "status": "ready",
      "data_age_days": 45,
      "current_metrics": {
        "hrv": 45.2,
        "sleep_score": 78,
        "resting_hr": 52
      },
      "observations": [
        {
          "category": "recovery",
          "priority": "high",
          "fact": "HRV is 13% below baseline"
        }
      ],
      "suggestions": [
        {
          "action": "rest_day",
          "confidence": 0.85,
          "reason": "Elevated overtraining risk"
        }
      ]
    }
    ```
    """
    validate_user_id(user_id)
    service = InsightsService(session)
    insights = await service.get_insights(user_id)

    # Convert to dict for JSON serialization
    return insights.model_dump(mode="json")


# Router for insights endpoints
insights_router = Router(
    path="/",
    route_handlers=[
        get_insights,
    ],
    guards=[per_user_api_key_guard],
    tags=["Insights"],
)
