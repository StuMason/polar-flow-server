"""MCP tool implementations over the health data.

Each tool opens its own short-lived database session (the MCP protocol layer
sits outside Litestar's dependency injection). Docstrings are surfaced to AI
assistants verbatim as tool descriptions, so they are written for the model:
say what the data means, its units, and when to reach for it.

Tool registration order (see ``server.py``) is the order clients see in
``tools/list`` — the SDK preserves it, and stable ordering keeps client-side
prompt caches warm.
"""

from datetime import date, timedelta
from typing import Annotated, Any, Literal

from pydantic import Field
from sqlalchemy import select

from polar_flow_server.mcp_server.context import resolve_scoped_user_id
from polar_flow_server.models.activity import Activity
from polar_flow_server.models.cardio_load import CardioLoad
from polar_flow_server.models.continuous_hr import ContinuousHeartRate
from polar_flow_server.models.ecg import ECG
from polar_flow_server.models.exercise import Exercise
from polar_flow_server.models.recharge import NightlyRecharge
from polar_flow_server.models.sleep import Sleep
from polar_flow_server.models.sleepwise_alertness import SleepWiseAlertness
from polar_flow_server.models.sleepwise_bedtime import SleepWiseBedtime
from polar_flow_server.models.spo2 import SpO2
from polar_flow_server.models.temperature import BodyTemperature, SkinTemperature

DaysParam = Annotated[
    int,
    Field(ge=1, le=365, description="How many days back from today to include (default 30)."),
]
UserIdParam = Annotated[
    str | None,
    Field(
        description=(
            "Polar user id. Leave unset with a user-scoped API key (the key decides), "
            "or on a single-user server. Only needed with a service-level key on a "
            "multi-user install."
        ),
    ),
]


async def get_health_insights(user_id: UserIdParam = None) -> dict[str, Any]:
    """Get a complete health and recovery assessment for the user.

    This is the best first call for any "how am I doing?" question. Returns
    current metrics (HRV in ms, sleep score 0-100, resting heart rate in bpm)
    compared against the user's own personal baselines, detected patterns
    (sleep-HRV correlation, overtraining risk, HRV/sleep trends), anomalies
    (metrics outside the user's normal bounds), plain-language observations,
    and actionable suggestions with confidence scores.

    The `status` field reports how much history the analytics have to work
    with: features unlock at 7 days (baselines), 21 days (patterns and
    anomalies), and 30 days (full baselines). Early in a user's history most
    sections will be empty - that is expected, not an error.
    """
    uid = await resolve_scoped_user_id(user_id)

    from polar_flow_server.core.database import async_session_maker
    from polar_flow_server.services.insights import InsightsService

    async with async_session_maker() as session:
        insights = await InsightsService(session).get_insights(uid)
    return insights.model_dump(mode="json")


async def get_sleep(days: DaysParam = 30, user_id: UserIdParam = None) -> dict[str, Any]:
    """Get nightly sleep records, most recent night first.

    Each record has the sleep date, sleep score (0-100, Polar's overall
    quality rating), hours asleep split by stage (light/deep/REM), overnight
    averages for HRV (ms), heart rate (bpm), breathing rate (breaths/min),
    and skin temperature deviation (deg C), plus sleep start/end times.
    Nights with no recorded sleep are simply absent - gaps in the dates mean
    the watch wasn't worn, not zero sleep.
    """
    uid = await resolve_scoped_user_id(user_id)

    from polar_flow_server.core.database import async_session_maker

    since = date.today() - timedelta(days=days)
    async with async_session_maker() as session:
        result = await session.execute(
            select(Sleep)
            .where(Sleep.user_id == uid, Sleep.date >= since)
            .order_by(Sleep.date.desc())
        )
        records = result.scalars().all()

    return {
        "days": days,
        "count": len(records),
        "records": [
            {
                "date": str(r.date),
                "sleep_score": r.sleep_score,
                "sleep_start_time": r.sleep_start_time,
                "sleep_end_time": r.sleep_end_time,
                "total_sleep_hours": _hours(r.total_sleep_seconds),
                "light_sleep_hours": _hours(r.light_sleep_seconds),
                "deep_sleep_hours": _hours(r.deep_sleep_seconds),
                "rem_sleep_hours": _hours(r.rem_sleep_seconds),
                "interruptions_hours": _hours(r.interruptions_seconds),
                "hrv_avg_ms": r.hrv_avg,
                "heart_rate_avg_bpm": r.heart_rate_avg,
                "breathing_rate_avg": r.breathing_rate_avg,
                "skin_temperature_avg": r.skin_temperature_avg,
            }
            for r in records
        ],
    }


async def get_recovery(days: DaysParam = 30, user_id: UserIdParam = None) -> dict[str, Any]:
    """Get recovery data: nightly recharge (ANS/HRV) and cardio load.

    `nightly_recharge` measures overnight autonomic nervous system recovery:
    ANS charge from -10 (very poor) to +10 (excellent) with a status label,
    overnight HRV average (ms), breathing rate, and heart rate. `cardio_load`
    measures training strain vs tolerance: a load ratio above ~1.3 means
    training load is rising faster than the body is adapting (overreaching
    risk); below ~0.8 means detraining. Use alongside get_sleep to judge
    readiness to train; both lists are most recent day first.
    """
    uid = await resolve_scoped_user_id(user_id)

    from polar_flow_server.core.database import async_session_maker

    since = date.today() - timedelta(days=days)
    async with async_session_maker() as session:
        recharge_result = await session.execute(
            select(NightlyRecharge)
            .where(NightlyRecharge.user_id == uid, NightlyRecharge.date >= since)
            .order_by(NightlyRecharge.date.desc())
        )
        recharge = recharge_result.scalars().all()
        cardio_result = await session.execute(
            select(CardioLoad)
            .where(CardioLoad.user_id == uid, CardioLoad.date >= since)
            .order_by(CardioLoad.date.desc())
        )
        cardio = cardio_result.scalars().all()

    return {
        "days": days,
        "nightly_recharge": [
            {
                "date": str(r.date),
                "ans_charge": r.ans_charge,
                "ans_charge_status": r.ans_charge_status,
                "hrv_avg_ms": r.hrv_avg,
                "breathing_rate_avg": r.breathing_rate_avg,
                "heart_rate_avg_bpm": r.heart_rate_avg,
            }
            for r in recharge
        ],
        "cardio_load": [
            {
                "date": str(r.date),
                "strain": r.strain,
                "tolerance": r.tolerance,
                "cardio_load": r.cardio_load,
                "cardio_load_ratio": (
                    round(r.cardio_load_ratio, 2) if r.cardio_load_ratio else None
                ),
                "cardio_load_status": r.cardio_load_status,
            }
            for r in cardio
        ],
    }


async def get_activity(days: DaysParam = 30, user_id: UserIdParam = None) -> dict[str, Any]:
    """Get daily activity summaries, most recent day first.

    Each record has steps, active and total calories (kcal), distance (km),
    active minutes, and Polar's activity score (0-100, how much of the daily
    activity goal was reached). Useful for spotting sedentary streaks or
    unusually big days when explaining recovery or sleep changes.
    """
    uid = await resolve_scoped_user_id(user_id)

    from polar_flow_server.core.database import async_session_maker

    since = date.today() - timedelta(days=days)
    async with async_session_maker() as session:
        result = await session.execute(
            select(Activity)
            .where(Activity.user_id == uid, Activity.date >= since)
            .order_by(Activity.date.desc())
        )
        records = result.scalars().all()

    return {
        "days": days,
        "count": len(records),
        "records": [
            {
                "date": str(r.date),
                "steps": r.steps,
                "calories_active": r.calories_active,
                "calories_total": r.calories_total,
                "distance_km": round(r.distance_meters / 1000, 2) if r.distance_meters else None,
                "active_minutes": (
                    round(r.active_time_seconds / 60, 1) if r.active_time_seconds else None
                ),
                "activity_score": r.activity_score,
            }
            for r in records
        ],
    }


async def get_exercises(
    days: DaysParam = 30,
    exercise_id: Annotated[
        str | None,
        Field(
            description=(
                "Pass an id from a previous get_exercises call to fetch that "
                "workout's full detail (speed, cadence, power, ascent/descent, "
                "notes) instead of the list."
            ),
        ),
    ] = None,
    user_id: UserIdParam = None,
) -> dict[str, Any]:
    """Get workout history, or one workout's full detail.

    Without `exercise_id`: recent workouts, newest first, each with sport,
    start time, duration (minutes), distance (km), calories, average/max
    heart rate (bpm), and training load. With `exercise_id`: every recorded
    metric for that single workout, including speed (m/s), cadence, power
    (watts), and elevation. Training load is Polar's cardio strain estimate
    for the session - compare against get_recovery's tolerance.
    """
    uid = await resolve_scoped_user_id(user_id)

    from polar_flow_server.core.database import async_session_maker

    if exercise_id is not None:
        async with async_session_maker() as session:
            result = await session.execute(
                select(Exercise).where(Exercise.user_id == uid, Exercise.id == exercise_id)
            )
            r = result.scalar_one_or_none()
        if r is None:
            raise ValueError(f"Exercise {exercise_id} not found")
        return {
            "id": r.id,
            "polar_exercise_id": r.polar_exercise_id,
            "start_time": str(r.start_time),
            "sport": r.sport,
            "duration_seconds": r.duration_seconds,
            "distance_meters": r.distance_meters,
            "calories": r.calories,
            "average_heart_rate_bpm": r.average_heart_rate,
            "max_heart_rate_bpm": r.max_heart_rate,
            "average_speed_mps": r.average_speed_mps,
            "max_speed_mps": r.max_speed_mps,
            "average_cadence": r.average_cadence,
            "max_cadence": r.max_cadence,
            "average_power_watts": r.average_power,
            "max_power_watts": r.max_power,
            "training_load": r.training_load,
            "ascent_meters": r.ascent_meters,
            "descent_meters": r.descent_meters,
            "notes": r.notes,
        }

    since = date.today() - timedelta(days=days)
    async with async_session_maker() as session:
        result = await session.execute(
            select(Exercise)
            .where(Exercise.user_id == uid, Exercise.start_time >= since)
            .order_by(Exercise.start_time.desc())
        )
        records = result.scalars().all()

    return {
        "days": days,
        "count": len(records),
        "records": [
            {
                "id": r.id,
                "start_time": str(r.start_time),
                "sport": r.sport,
                "duration_minutes": (
                    round(r.duration_seconds / 60, 1) if r.duration_seconds else None
                ),
                "distance_km": round(r.distance_meters / 1000, 2) if r.distance_meters else None,
                "calories": r.calories,
                "average_heart_rate_bpm": r.average_heart_rate,
                "max_heart_rate_bpm": r.max_heart_rate,
                "training_load": r.training_load,
            }
            for r in records
        ],
    }


BiosensingMetric = Literal[
    "spo2",
    "ecg",
    "body_temperature",
    "skin_temperature",
    "heart_rate",
    "alertness",
    "bedtime",
]


async def get_biosensing(
    metric: Annotated[
        BiosensingMetric,
        Field(description="Which biosensing stream to read."),
    ],
    days: DaysParam = 30,
    user_id: UserIdParam = None,
) -> dict[str, Any]:
    """Get one biosensing data stream, most recent first.

    Metrics: `spo2` blood oxygen tests (percent, plus HR/HRV during the
    test); `ecg` measurement summaries (HR, HRV in ms, RRI); `body_temperature`
    spot measurements (deg C, min/avg/max); `skin_temperature` nightly values
    with deviation from the user's baseline and an is_elevated flag (useful
    for illness or cycle tracking); `heart_rate` daily continuous-HR
    summaries (min/avg/max bpm - the daily min approximates true resting
    HR); `alertness` SleepWise predicted alertness periods (grade and
    classification); `bedtime` SleepWise circadian bedtime recommendations
    (preferred sleep window and gate times).
    """
    uid = await resolve_scoped_user_id(user_id)

    from polar_flow_server.core.database import async_session_maker

    since = date.today() - timedelta(days=days)
    async with async_session_maker() as session:
        records = await _query_biosensing(session, metric, uid, since)

    return {"metric": metric, "days": days, "count": len(records), "records": records}


async def get_baselines(user_id: UserIdParam = None) -> dict[str, Any]:
    """Get the user's personal baselines for key health metrics.

    Baselines exist for hrv_rmssd, sleep_score, resting_hr, training_load,
    and training_load_ratio. Each has rolling averages (7d/30d/90d), median
    and IQR statistics with lower/upper anomaly bounds (values outside them
    are abnormal FOR THIS USER), min/max, sample count, and a status that
    says how much history backs it (ready/partial/insufficient). Use these
    to judge whether a current reading from other tools is meaningfully
    high or low rather than comparing to population norms.
    """
    uid = await resolve_scoped_user_id(user_id)

    from polar_flow_server.core.database import async_session_maker
    from polar_flow_server.services.baseline import BaselineService

    async with async_session_maker() as session:
        baselines = await BaselineService(session).get_user_baselines(uid)

    return {
        "count": len(baselines),
        "baselines": [
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
        ],
    }


async def get_patterns(user_id: UserIdParam = None) -> dict[str, Any]:
    """Get detected patterns and current anomalies.

    `patterns` are stored analyses across the user's history:
    sleep_hrv_correlation (does better sleep raise their HRV),
    overtraining_risk (0-100 composite with contributing factors and
    recovery recommendations in details), hrv_trend and sleep_trend (7-day
    vs 30-day direction, as a percentage). Each has a score, confidence,
    significance level, and interpretation details. `anomalies` re-checks
    the latest metric values against baseline IQR bounds right now -
    severity "warning" is outside 1.5x IQR, "critical" outside 3x IQR.
    Patterns need ~21 days of history; both lists are empty before that.
    """
    uid = await resolve_scoped_user_id(user_id)

    from polar_flow_server.core.database import async_session_maker
    from polar_flow_server.services.pattern import AnomalyService, PatternService

    async with async_session_maker() as session:
        patterns = await PatternService(session).get_user_patterns(uid)
        anomalies = await AnomalyService(session).detect_all_anomalies(uid)

    return {
        "patterns": [
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
        ],
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
    }


async def _query_biosensing(
    session: Any, metric: str, uid: str, since: date
) -> list[dict[str, Any]]:
    """Run the per-metric biosensing query and serialize the rows."""
    if metric == "spo2":
        rows = await session.execute(
            select(SpO2)
            .where(SpO2.user_id == uid, SpO2.test_time >= since)
            .order_by(SpO2.test_time.desc())
        )
        return [
            {
                "test_time": str(r.test_time),
                "blood_oxygen_percent": r.blood_oxygen_percent,
                "spo2_class": r.spo2_class,
                "avg_heart_rate_bpm": r.avg_heart_rate,
                "hrv_ms": r.hrv_ms,
                "altitude_meters": r.altitude_meters,
            }
            for r in rows.scalars().all()
        ]
    if metric == "ecg":
        rows = await session.execute(
            select(ECG)
            .where(ECG.user_id == uid, ECG.test_time >= since)
            .order_by(ECG.test_time.desc())
        )
        return [
            {
                "test_time": str(r.test_time),
                "avg_heart_rate_bpm": r.avg_heart_rate,
                "hrv_ms": r.hrv_ms,
                "hrv_level": r.hrv_level,
                "rri_ms": r.rri_ms,
                "duration_seconds": r.duration_seconds,
                "sample_count": r.sample_count,
            }
            for r in rows.scalars().all()
        ]
    if metric == "body_temperature":
        rows = await session.execute(
            select(BodyTemperature)
            .where(BodyTemperature.user_id == uid, BodyTemperature.start_time >= since)
            .order_by(BodyTemperature.start_time.desc())
        )
        return [
            {
                "start_time": str(r.start_time),
                "end_time": str(r.end_time),
                "measurement_type": r.measurement_type,
                "sensor_location": r.sensor_location,
                "temp_min_celsius": r.temp_min,
                "temp_avg_celsius": r.temp_avg,
                "temp_max_celsius": r.temp_max,
                "sample_count": r.sample_count,
            }
            for r in rows.scalars().all()
        ]
    if metric == "skin_temperature":
        rows = await session.execute(
            select(SkinTemperature)
            .where(SkinTemperature.user_id == uid, SkinTemperature.sleep_date >= since)
            .order_by(SkinTemperature.sleep_date.desc())
        )
        return [
            {
                "sleep_date": str(r.sleep_date),
                "temperature_celsius": r.temperature_celsius,
                "deviation_from_baseline": r.deviation_from_baseline,
                "is_elevated": r.is_elevated,
            }
            for r in rows.scalars().all()
        ]
    if metric == "heart_rate":
        rows = await session.execute(
            select(ContinuousHeartRate)
            .where(ContinuousHeartRate.user_id == uid, ContinuousHeartRate.date >= since)
            .order_by(ContinuousHeartRate.date.desc())
        )
        return [
            {
                "date": str(r.date),
                "hr_min_bpm": r.hr_min,
                "hr_avg_bpm": r.hr_avg,
                "hr_max_bpm": r.hr_max,
                "sample_count": r.sample_count,
            }
            for r in rows.scalars().all()
        ]
    if metric == "alertness":
        rows = await session.execute(
            select(SleepWiseAlertness)
            .where(
                SleepWiseAlertness.user_id == uid,
                SleepWiseAlertness.period_start_time >= since,
            )
            .order_by(SleepWiseAlertness.period_start_time.desc())
        )
        return [
            {
                "period_start_time": str(r.period_start_time),
                "period_end_time": str(r.period_end_time),
                "grade": r.grade,
                "grade_classification": r.grade_classification,
            }
            for r in rows.scalars().all()
        ]
    # bedtime - the Literal type means no other value can reach here
    rows = await session.execute(
        select(SleepWiseBedtime)
        .where(
            SleepWiseBedtime.user_id == uid,
            SleepWiseBedtime.period_start_time >= since,
        )
        .order_by(SleepWiseBedtime.period_start_time.desc())
    )
    return [
        {
            "period_start_time": str(r.period_start_time),
            "period_end_time": str(r.period_end_time),
            "preferred_sleep_start": str(r.preferred_sleep_start),
            "preferred_sleep_end": str(r.preferred_sleep_end),
            "sleep_gate_start": str(r.sleep_gate_start),
            "sleep_gate_end": str(r.sleep_gate_end),
            "quality": r.quality,
        }
        for r in rows.scalars().all()
    ]


def _hours(seconds: int | None) -> float | None:
    """Convert a seconds count to hours rounded to 2 decimals."""
    return round(seconds / 3600, 2) if seconds else None
