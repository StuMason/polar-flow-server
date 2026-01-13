"""Pattern detection and anomaly API endpoints."""

import re
from typing import Any

from litestar import Router, get, post
from litestar.exceptions import NotFoundException, ValidationException
from litestar.status_codes import HTTP_200_OK
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.core.auth import per_user_api_key_guard
from polar_flow_server.models.pattern import PatternName
from polar_flow_server.services.pattern import AnomalyService, PatternService

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


@get("/users/{user_id:str}/patterns", status_code=HTTP_200_OK)
async def get_patterns(
    user_id: str,
    session: AsyncSession,
) -> list[dict[str, Any]]:
    """Get all detected patterns for a user.

    Returns correlations, trends, and composite scores including:
    - Sleep-HRV correlation
    - Overtraining risk score
    - HRV and sleep trends

    Patterns include:
    - Score (correlation coefficient, risk score, or trend percentage)
    - Confidence level
    - Significance (high, medium, low, insufficient)
    - Detailed interpretation
    """
    validate_user_id(user_id)
    service = PatternService(session)
    patterns = await service.get_user_patterns(user_id)

    return [
        {
            "pattern_type": p.pattern_type,
            "pattern_name": p.pattern_name,
            "score": p.score,
            "confidence": p.confidence,
            "significance": p.significance,
            "metrics_involved": p.metrics_involved,
            "sample_count": p.sample_count,
            "details": p.details,
            "analyzed_at": p.analyzed_at.isoformat() if p.analyzed_at else None,
        }
        for p in patterns
    ]


@get("/users/{user_id:str}/patterns/{pattern_name:str}", status_code=HTTP_200_OK)
async def get_pattern_by_name(
    user_id: str,
    pattern_name: str,
    session: AsyncSession,
) -> dict[str, Any]:
    """Get a specific pattern by name.

    Valid pattern names:
    - sleep_hrv_correlation: Correlation between sleep quality and HRV
    - overtraining_risk: Multi-metric overtraining risk score
    - hrv_trend: 7-day HRV trend vs 30-day baseline
    - sleep_trend: 7-day sleep score trend vs 30-day baseline

    Raises:
        NotFoundException: If pattern name is invalid or pattern not found
    """
    validate_user_id(user_id)

    # Validate pattern name
    valid_names = [p.value for p in PatternName]
    if pattern_name not in valid_names:
        raise NotFoundException(
            f"Invalid pattern name '{pattern_name}'. Valid names: {', '.join(valid_names)}"
        )

    service = PatternService(session)
    pattern = await service.get_pattern(user_id, pattern_name)

    if not pattern:
        raise NotFoundException(f"Pattern '{pattern_name}' not found for user")

    return {
        "pattern_type": pattern.pattern_type,
        "pattern_name": pattern.pattern_name,
        "score": pattern.score,
        "confidence": pattern.confidence,
        "significance": pattern.significance,
        "metrics_involved": pattern.metrics_involved,
        "sample_count": pattern.sample_count,
        "details": pattern.details,
        "analyzed_at": pattern.analyzed_at.isoformat() if pattern.analyzed_at else None,
    }


@post("/users/{user_id:str}/patterns/detect", status_code=HTTP_200_OK)
async def detect_patterns(
    user_id: str,
    session: AsyncSession,
) -> dict[str, Any]:
    """Trigger pattern detection for a user.

    Analyzes historical data to detect:
    - Sleep-HRV correlation (Spearman correlation)
    - Overtraining risk (multi-metric composite score)
    - HRV trend (7-day vs 30-day baseline)
    - Sleep trend (7-day vs 30-day baseline)

    Returns the significance level of each detected pattern.
    """
    validate_user_id(user_id)
    service = PatternService(session)
    results = await service.detect_all_patterns(user_id)

    return {
        "user_id": user_id,
        "patterns_detected": results,
    }


@get("/users/{user_id:str}/anomalies", status_code=HTTP_200_OK)
async def get_anomalies(
    user_id: str,
    session: AsyncSession,
) -> dict[str, Any]:
    """Get all detected anomalies for a user.

    Scans all metrics against stored baselines and returns any values
    that fall outside normal IQR bounds.

    Anomaly severity levels:
    - warning: Value outside Q1 - 1.5×IQR to Q3 + 1.5×IQR
    - critical: Value outside Q1 - 3×IQR to Q3 + 3×IQR

    Returns empty list if no baselines exist or no anomalies detected.
    """
    validate_user_id(user_id)
    service = AnomalyService(session)
    anomalies = await service.detect_all_anomalies(user_id)

    return {
        "user_id": user_id,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
    }


# Router for patterns endpoints
patterns_router = Router(
    path="/",
    route_handlers=[
        get_patterns,
        get_pattern_by_name,
        detect_patterns,
        get_anomalies,
    ],
    guards=[per_user_api_key_guard],
    tags=["Patterns"],
)
