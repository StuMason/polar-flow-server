"""Baseline analytics API endpoints."""

from datetime import UTC, datetime, timedelta
from typing import Any

from litestar import Router, get, post
from litestar.status_codes import HTTP_200_OK
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.core.auth import per_user_api_key_guard
from polar_flow_server.models.activity import Activity
from polar_flow_server.models.baseline import MetricName
from polar_flow_server.models.cardio_load import CardioLoad
from polar_flow_server.models.recharge import NightlyRecharge
from polar_flow_server.models.sleep import Sleep
from polar_flow_server.services.baseline import BaselineService

# Feature unlock thresholds (days of data required)
FEATURE_THRESHOLDS = {
    "basic_stats": 7,
    "trend_analysis": 14,
    "personalized_baselines": 21,
    "predictive_models": 30,
    "advanced_ml": 60,
    "long_term_patterns": 90,
}


@get("/users/{user_id:str}/baselines", status_code=HTTP_200_OK)
async def get_baselines(
    user_id: str,
    session: AsyncSession,
) -> list[dict[str, Any]]:
    """Get all computed baselines for a user.

    Returns personal baselines for health metrics (HRV, sleep score,
    resting HR, training load). Use these for anomaly detection and
    personalized insights.

    Baselines include:
    - Rolling averages (7d, 30d, 90d)
    - IQR statistics (Q1, Q3, median) for anomaly detection
    - Status (ready, partial, insufficient based on data availability)
    """
    service = BaselineService(session)
    baselines = await service.get_user_baselines(user_id)

    return [
        {
            "metric_name": b.metric_name,
            "baseline_value": b.baseline_value,
            "baseline_7d": b.baseline_7d,
            "baseline_30d": b.baseline_30d,
            "baseline_90d": b.baseline_90d,
            "median": b.median_value,
            "q1": b.q1,
            "q3": b.q3,
            "iqr": b.iqr,
            "std_dev": b.std_dev,
            "min": b.min_value,
            "max": b.max_value,
            "lower_bound": b.lower_bound,
            "upper_bound": b.upper_bound,
            "sample_count": b.sample_count,
            "status": b.status,
            "data_start_date": str(b.data_start_date) if b.data_start_date else None,
            "data_end_date": str(b.data_end_date) if b.data_end_date else None,
            "calculated_at": b.calculated_at.isoformat() if b.calculated_at else None,
        }
        for b in baselines
    ]


@get("/users/{user_id:str}/baselines/{metric_name:str}", status_code=HTTP_200_OK)
async def get_baseline_by_metric(
    user_id: str,
    metric_name: str,
    session: AsyncSession,
) -> dict[str, Any] | None:
    """Get a specific baseline by metric name.

    Valid metric names:
    - hrv_rmssd: Heart Rate Variability (RMSSD)
    - sleep_score: Overall sleep quality score
    - resting_hr: Resting heart rate
    - training_load: Training load (cardio load)
    - training_load_ratio: Acute:chronic load ratio
    """
    try:
        metric = MetricName(metric_name)
    except ValueError:
        return None

    service = BaselineService(session)
    baseline = await service.get_baseline(user_id, metric)

    if not baseline:
        return None

    return {
        "metric_name": baseline.metric_name,
        "baseline_value": baseline.baseline_value,
        "baseline_7d": baseline.baseline_7d,
        "baseline_30d": baseline.baseline_30d,
        "baseline_90d": baseline.baseline_90d,
        "median": baseline.median_value,
        "q1": baseline.q1,
        "q3": baseline.q3,
        "iqr": baseline.iqr,
        "std_dev": baseline.std_dev,
        "min": baseline.min_value,
        "max": baseline.max_value,
        "lower_bound": baseline.lower_bound,
        "upper_bound": baseline.upper_bound,
        "sample_count": baseline.sample_count,
        "status": baseline.status,
        "data_start_date": str(baseline.data_start_date) if baseline.data_start_date else None,
        "data_end_date": str(baseline.data_end_date) if baseline.data_end_date else None,
        "calculated_at": baseline.calculated_at.isoformat() if baseline.calculated_at else None,
    }


@post("/users/{user_id:str}/baselines/calculate", status_code=HTTP_200_OK)
async def calculate_baselines(
    user_id: str,
    session: AsyncSession,
) -> dict[str, Any]:
    """Trigger baseline calculation for a user.

    Calculates all baselines from historical data:
    - HRV RMSSD from nightly recharge
    - Sleep score from sleep data
    - Resting heart rate from nightly recharge
    - Training load and ratio from cardio load data

    Returns the status of each calculated baseline.
    """
    service = BaselineService(session)
    results = await service.calculate_all_baselines(user_id)

    return {
        "user_id": user_id,
        "baselines_calculated": results,
    }


@get(
    "/users/{user_id:str}/baselines/check/{metric_name:str}/{value:float}", status_code=HTTP_200_OK
)
async def check_anomaly(
    user_id: str,
    metric_name: str,
    value: float,
    session: AsyncSession,
) -> dict[str, Any]:
    """Check if a value is anomalous for a given metric.

    Uses IQR-based anomaly detection:
    - Warning: value outside Q1 - 1.5*IQR to Q3 + 1.5*IQR
    - Critical: value outside Q1 - 3*IQR to Q3 + 3*IQR

    Example:
        GET /users/123/baselines/check/hrv_rmssd/25.5

    Returns:
        {
            "is_anomaly": true,
            "severity": "warning",
            "baseline": 42.3,
            "lower_bound": 28.1,
            "upper_bound": 56.5
        }
    """
    try:
        metric = MetricName(metric_name)
    except ValueError:
        return {
            "error": f"Unknown metric: {metric_name}",
            "valid_metrics": [m.value for m in MetricName],
        }

    service = BaselineService(session)
    baseline = await service.get_baseline(user_id, metric)

    if not baseline:
        return {
            "is_anomaly": False,
            "reason": "No baseline data available",
            "status": "insufficient",
        }

    is_anomaly, severity = baseline.is_anomaly(value)

    return {
        "value": value,
        "metric_name": metric_name,
        "is_anomaly": is_anomaly,
        "severity": severity,
        "baseline": baseline.baseline_value,
        "baseline_7d": baseline.baseline_7d,
        "lower_bound": baseline.lower_bound,
        "upper_bound": baseline.upper_bound,
        "status": baseline.status,
    }


@get("/users/{user_id:str}/analytics/status", status_code=HTTP_200_OK)
async def get_analytics_status(
    user_id: str,
    session: AsyncSession,
) -> dict[str, Any]:
    """Get analytics readiness status and available features for a user.

    Returns:
    - Days of data available for each metric type
    - Which analytics features are unlocked
    - Progress toward unlocking additional features

    Feature unlock timeline:
    - 7 days: Basic statistics, daily tracking
    - 14 days: Trend analysis, basic anomaly alerts
    - 21 days: Reliable correlations, personalized baselines
    - 30 days: Predictive models, outcome forecasting
    - 60 days: Advanced ML models, behavior patterns
    - 90 days: Long-term pattern recognition
    """
    today = datetime.now(UTC).date()

    # Count days of data for each data type
    data_counts: dict[str, int] = {}

    # Sleep data
    stmt = (
        select(func.count(func.distinct(Sleep.date)))
        .where(Sleep.user_id == user_id)
        .where(Sleep.date >= today - timedelta(days=90))
    )
    result = await session.execute(stmt)
    data_counts["sleep"] = result.scalar() or 0

    # Nightly recharge (HRV)
    stmt = (
        select(func.count(func.distinct(NightlyRecharge.date)))
        .where(NightlyRecharge.user_id == user_id)
        .where(NightlyRecharge.date >= today - timedelta(days=90))
    )
    result = await session.execute(stmt)
    data_counts["recharge"] = result.scalar() or 0

    # Activity
    stmt = (
        select(func.count(func.distinct(Activity.date)))
        .where(Activity.user_id == user_id)
        .where(Activity.date >= today - timedelta(days=90))
    )
    result = await session.execute(stmt)
    data_counts["activity"] = result.scalar() or 0

    # Cardio load
    stmt = (
        select(func.count(func.distinct(CardioLoad.date)))
        .where(CardioLoad.user_id == user_id)
        .where(CardioLoad.date >= today - timedelta(days=90))
    )
    result = await session.execute(stmt)
    data_counts["cardio_load"] = result.scalar() or 0

    # Minimum data days across all sources (for feature unlock)
    min_days = min(data_counts.values()) if data_counts.values() else 0

    # Determine unlocked features
    features_available: dict[str, bool] = {}
    for feature, threshold in FEATURE_THRESHOLDS.items():
        features_available[feature] = min_days >= threshold

    # Calculate unlock progress
    unlock_progress: dict[str, dict[str, Any]] = {}
    for feature, threshold in FEATURE_THRESHOLDS.items():
        if min_days >= threshold:
            unlock_progress[feature] = {
                "unlocked": True,
                "days_required": threshold,
                "days_remaining": 0,
                "progress_percent": 100,
            }
        else:
            unlock_progress[feature] = {
                "unlocked": False,
                "days_required": threshold,
                "days_remaining": threshold - min_days,
                "progress_percent": round((min_days / threshold) * 100, 1),
            }

    return {
        "user_id": user_id,
        "data_days": data_counts,
        "min_data_days": min_days,
        "features_available": features_available,
        "unlock_progress": unlock_progress,
        "recommendations": _get_recommendations(min_days, features_available),
    }


def _get_recommendations(min_days: int, features: dict[str, bool]) -> list[str]:
    """Generate recommendations based on data availability."""
    recommendations = []

    if min_days < 7:
        recommendations.append(
            f"Keep syncing! {7 - min_days} more days until basic statistics unlock."
        )
    elif not features["trend_analysis"]:
        recommendations.append(
            f"Trend analysis unlocks in {14 - min_days} days. Keep wearing your device!"
        )
    elif not features["personalized_baselines"]:
        recommendations.append(
            f"Personalized baselines unlock in {21 - min_days} days. "
            "This enables accurate anomaly detection."
        )
    elif not features["predictive_models"]:
        recommendations.append(
            f"Predictive models unlock in {30 - min_days} days. "
            "Soon we can forecast recovery and readiness!"
        )
    elif not features["advanced_ml"]:
        recommendations.append("Great progress! Advanced ML features unlock after 60 days of data.")
    else:
        recommendations.append(
            "Excellent! All features are unlocked. Full analytics suite available."
        )

    return recommendations


# Router for baselines endpoints
baselines_router = Router(
    path="/",
    route_handlers=[
        get_baselines,
        get_baseline_by_metric,
        calculate_baselines,
        check_anomaly,
        get_analytics_status,
    ],
    guards=[per_user_api_key_guard],
    tags=["Baselines"],
)
