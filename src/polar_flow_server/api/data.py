"""Comprehensive data API endpoints for all Polar data types."""

from datetime import date, timedelta
from typing import Annotated, Any

from litestar import Router, get
from litestar.params import Parameter
from litestar.status_codes import HTTP_200_OK
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.models.activity import Activity
from polar_flow_server.models.activity_samples import ActivitySamples
from polar_flow_server.models.cardio_load import CardioLoad
from polar_flow_server.models.continuous_hr import ContinuousHeartRate
from polar_flow_server.models.ecg import ECG
from polar_flow_server.models.exercise import Exercise
from polar_flow_server.models.recharge import NightlyRecharge
from polar_flow_server.models.sleepwise_alertness import SleepWiseAlertness
from polar_flow_server.models.sleepwise_bedtime import SleepWiseBedtime
from polar_flow_server.models.spo2 import SpO2
from polar_flow_server.models.temperature import BodyTemperature, SkinTemperature

# ==============================================================================
# Activity Endpoints
# ==============================================================================


@get("/users/{user_id:str}/activity", status_code=HTTP_200_OK)
async def get_activity_list(
    user_id: str,
    session: AsyncSession,
    days: Annotated[int, Parameter(query="days", default=30, ge=1, le=365)] = 30,
) -> list[dict[str, Any]]:
    """Get daily activity data for a user.

    Returns steps, calories, active time, and distance for each day.
    """
    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(Activity)
        .where(Activity.user_id == user_id)
        .where(Activity.date >= since_date)
        .order_by(Activity.date.desc())
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    return [
        {
            "date": str(r.date),
            "steps": r.steps,
            "calories_active": r.calories_active,
            "calories_total": r.calories_total,
            "distance_km": round(r.distance_meters / 1000, 2) if r.distance_meters else None,
            "active_minutes": round(r.active_time_seconds / 60, 1)
            if r.active_time_seconds
            else None,
            "activity_score": r.activity_score,
        }
        for r in records
    ]


@get("/users/{user_id:str}/activity/{target_date:str}", status_code=HTTP_200_OK)
async def get_activity_by_date(
    user_id: str,
    target_date: str,
    session: AsyncSession,
) -> dict[str, Any] | None:
    """Get activity data for a specific date."""
    stmt = select(Activity).where(
        Activity.user_id == user_id,
        Activity.date == date.fromisoformat(target_date),
    )
    result = await session.execute(stmt)
    r = result.scalar_one_or_none()

    if not r:
        return None

    return {
        "date": str(r.date),
        "steps": r.steps,
        "calories_active": r.calories_active,
        "calories_total": r.calories_total,
        "distance_meters": r.distance_meters,
        "active_time_seconds": r.active_time_seconds,
        "activity_score": r.activity_score,
        "inactivity_alerts": r.inactivity_alerts,
    }


# ==============================================================================
# Nightly Recharge (HRV) Endpoints
# ==============================================================================


@get("/users/{user_id:str}/recharge", status_code=HTTP_200_OK)
async def get_recharge_list(
    user_id: str,
    session: AsyncSession,
    days: Annotated[int, Parameter(query="days", default=30, ge=1, le=365)] = 30,
) -> list[dict[str, Any]]:
    """Get nightly recharge data (HRV, ANS charge, recovery status)."""
    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(NightlyRecharge)
        .where(NightlyRecharge.user_id == user_id)
        .where(NightlyRecharge.date >= since_date)
        .order_by(NightlyRecharge.date.desc())
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    return [
        {
            "date": str(r.date),
            "hrv_avg": r.hrv_avg,
            "ans_charge": r.ans_charge,
            "nightly_recharge_status": r.nightly_recharge_status,
            "breathing_rate_avg": r.breathing_rate_avg,
            "heart_rate_avg": r.heart_rate_avg,
        }
        for r in records
    ]


# ==============================================================================
# Cardio Load Endpoints
# ==============================================================================


@get("/users/{user_id:str}/cardio-load", status_code=HTTP_200_OK)
async def get_cardio_load_list(
    user_id: str,
    session: AsyncSession,
    days: Annotated[int, Parameter(query="days", default=30, ge=1, le=365)] = 30,
) -> list[dict[str, Any]]:
    """Get cardio load data (strain, tolerance, load ratio)."""
    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(CardioLoad)
        .where(CardioLoad.user_id == user_id)
        .where(CardioLoad.date >= since_date)
        .order_by(CardioLoad.date.desc())
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    return [
        {
            "date": str(r.date),
            "strain": r.strain,
            "tolerance": r.tolerance,
            "cardio_load": r.cardio_load,
            "cardio_load_ratio": round(r.cardio_load_ratio, 2) if r.cardio_load_ratio else None,
            "cardio_load_status": r.cardio_load_status,
        }
        for r in records
    ]


# ==============================================================================
# Heart Rate Endpoints
# ==============================================================================


@get("/users/{user_id:str}/heart-rate", status_code=HTTP_200_OK)
async def get_heart_rate_list(
    user_id: str,
    session: AsyncSession,
    days: Annotated[int, Parameter(query="days", default=30, ge=1, le=365)] = 30,
) -> list[dict[str, Any]]:
    """Get daily heart rate summaries (min/avg/max)."""
    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(ContinuousHeartRate)
        .where(ContinuousHeartRate.user_id == user_id)
        .where(ContinuousHeartRate.date >= since_date)
        .order_by(ContinuousHeartRate.date.desc())
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    return [
        {
            "date": str(r.date),
            "hr_min": r.hr_min,
            "hr_avg": r.hr_avg,
            "hr_max": r.hr_max,
            "sample_count": r.sample_count,
        }
        for r in records
    ]


# ==============================================================================
# Exercise Endpoints
# ==============================================================================


@get("/users/{user_id:str}/exercises", status_code=HTTP_200_OK)
async def get_exercises_list(
    user_id: str,
    session: AsyncSession,
    days: Annotated[int, Parameter(query="days", default=30, ge=1, le=365)] = 30,
) -> list[dict[str, Any]]:
    """Get exercise/workout history."""
    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(Exercise)
        .where(Exercise.user_id == user_id)
        .where(Exercise.start_time >= since_date)
        .order_by(Exercise.start_time.desc())
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    return [
        {
            "id": r.id,
            "polar_exercise_id": r.polar_exercise_id,
            "start_time": str(r.start_time),
            "sport": r.sport,
            "duration_minutes": round(r.duration_seconds / 60, 1) if r.duration_seconds else None,
            "distance_km": round(r.distance_meters / 1000, 2) if r.distance_meters else None,
            "calories": r.calories,
            "avg_heart_rate": r.avg_heart_rate,
            "max_heart_rate": r.max_heart_rate,
            "training_load": r.training_load,
        }
        for r in records
    ]


@get("/users/{user_id:str}/exercises/{exercise_id:int}", status_code=HTTP_200_OK)
async def get_exercise_detail(
    user_id: str,
    exercise_id: int,
    session: AsyncSession,
) -> dict[str, Any] | None:
    """Get detailed exercise data."""
    stmt = select(Exercise).where(
        Exercise.user_id == user_id,
        Exercise.id == exercise_id,
    )
    result = await session.execute(stmt)
    r = result.scalar_one_or_none()

    if not r:
        return None

    return {
        "id": r.id,
        "polar_exercise_id": r.polar_exercise_id,
        "start_time": str(r.start_time),
        "sport": r.sport,
        "duration_seconds": r.duration_seconds,
        "distance_meters": r.distance_meters,
        "calories": r.calories,
        "avg_heart_rate": r.avg_heart_rate,
        "max_heart_rate": r.max_heart_rate,
        "avg_speed": r.avg_speed,
        "max_speed": r.max_speed,
        "avg_cadence": r.avg_cadence,
        "max_cadence": r.max_cadence,
        "avg_power": r.avg_power,
        "max_power": r.max_power,
        "training_load": r.training_load,
        "ascent": r.ascent,
        "descent": r.descent,
        "notes": r.notes,
    }


# ==============================================================================
# SleepWise Endpoints
# ==============================================================================


@get("/users/{user_id:str}/sleepwise/alertness", status_code=HTTP_200_OK)
async def get_alertness_list(
    user_id: str,
    session: AsyncSession,
    days: Annotated[int, Parameter(query="days", default=7, ge=1, le=30)] = 7,
) -> list[dict[str, Any]]:
    """Get SleepWise alertness predictions."""
    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(SleepWiseAlertness)
        .where(SleepWiseAlertness.user_id == user_id)
        .where(SleepWiseAlertness.period_start_time >= since_date)
        .order_by(SleepWiseAlertness.period_start_time.desc())
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    return [
        {
            "period_start_time": str(r.period_start_time),
            "period_end_time": str(r.period_end_time),
            "grade": r.grade,
            "alertness_level": r.alertness_level,
        }
        for r in records
    ]


@get("/users/{user_id:str}/sleepwise/bedtime", status_code=HTTP_200_OK)
async def get_bedtime_list(
    user_id: str,
    session: AsyncSession,
    days: Annotated[int, Parameter(query="days", default=7, ge=1, le=30)] = 7,
) -> list[dict[str, Any]]:
    """Get SleepWise circadian bedtime recommendations."""
    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(SleepWiseBedtime)
        .where(SleepWiseBedtime.user_id == user_id)
        .where(SleepWiseBedtime.period_start_time >= since_date)
        .order_by(SleepWiseBedtime.period_start_time.desc())
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    return [
        {
            "period_start_time": str(r.period_start_time),
            "period_end_time": str(r.period_end_time),
            "bedtime_optimal": str(r.bedtime_optimal) if r.bedtime_optimal else None,
            "bedtime_early": str(r.bedtime_early) if r.bedtime_early else None,
            "bedtime_late": str(r.bedtime_late) if r.bedtime_late else None,
        }
        for r in records
    ]


# ==============================================================================
# Activity Samples Endpoints
# ==============================================================================


@get("/users/{user_id:str}/activity-samples", status_code=HTTP_200_OK)
async def get_activity_samples_list(
    user_id: str,
    session: AsyncSession,
    days: Annotated[int, Parameter(query="days", default=7, ge=1, le=30)] = 7,
) -> list[dict[str, Any]]:
    """Get minute-by-minute activity samples."""
    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(ActivitySamples)
        .where(ActivitySamples.user_id == user_id)
        .where(ActivitySamples.date >= since_date)
        .order_by(ActivitySamples.date.desc())
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    return [
        {
            "date": str(r.date),
            "sample_count": r.sample_count,
            "total_steps": r.total_steps,
            "has_samples": r.samples_json is not None,
        }
        for r in records
    ]


# ==============================================================================
# Biosensing Endpoints (SpO2, ECG, Temperature)
# ==============================================================================


@get("/users/{user_id:str}/spo2", status_code=HTTP_200_OK)
async def get_spo2_list(
    user_id: str,
    session: AsyncSession,
    days: Annotated[int, Parameter(query="days", default=30, ge=1, le=365)] = 30,
) -> list[dict[str, Any]]:
    """Get SpO2 (blood oxygen) measurements."""
    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(SpO2)
        .where(SpO2.user_id == user_id)
        .where(SpO2.test_time >= since_date)
        .order_by(SpO2.test_time.desc())
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    return [
        {
            "test_time": str(r.test_time),
            "blood_oxygen_percent": r.blood_oxygen_percent,
            "spo2_class": r.spo2_class,
            "avg_heart_rate": r.avg_heart_rate,
            "hrv_ms": r.hrv_ms,
            "altitude_meters": r.altitude_meters,
        }
        for r in records
    ]


@get("/users/{user_id:str}/ecg", status_code=HTTP_200_OK)
async def get_ecg_list(
    user_id: str,
    session: AsyncSession,
    days: Annotated[int, Parameter(query="days", default=30, ge=1, le=365)] = 30,
) -> list[dict[str, Any]]:
    """Get ECG measurement summaries."""
    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(ECG)
        .where(ECG.user_id == user_id)
        .where(ECG.test_time >= since_date)
        .order_by(ECG.test_time.desc())
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    return [
        {
            "test_time": str(r.test_time),
            "avg_heart_rate": r.avg_heart_rate,
            "hrv_ms": r.hrv_ms,
            "hrv_level": r.hrv_level,
            "rri_ms": r.rri_ms,
            "duration_seconds": r.duration_seconds,
            "sample_count": r.sample_count,
        }
        for r in records
    ]


@get("/users/{user_id:str}/temperature/body", status_code=HTTP_200_OK)
async def get_body_temperature_list(
    user_id: str,
    session: AsyncSession,
    days: Annotated[int, Parameter(query="days", default=30, ge=1, le=365)] = 30,
) -> list[dict[str, Any]]:
    """Get body temperature measurements."""
    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(BodyTemperature)
        .where(BodyTemperature.user_id == user_id)
        .where(BodyTemperature.start_time >= since_date)
        .order_by(BodyTemperature.start_time.desc())
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    return [
        {
            "start_time": str(r.start_time),
            "end_time": str(r.end_time),
            "measurement_type": r.measurement_type,
            "sensor_location": r.sensor_location,
            "temp_min": r.temp_min,
            "temp_avg": r.temp_avg,
            "temp_max": r.temp_max,
            "sample_count": r.sample_count,
        }
        for r in records
    ]


@get("/users/{user_id:str}/temperature/skin", status_code=HTTP_200_OK)
async def get_skin_temperature_list(
    user_id: str,
    session: AsyncSession,
    days: Annotated[int, Parameter(query="days", default=30, ge=1, le=365)] = 30,
) -> list[dict[str, Any]]:
    """Get skin temperature measurements."""
    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(SkinTemperature)
        .where(SkinTemperature.user_id == user_id)
        .where(SkinTemperature.sleep_date >= since_date)
        .order_by(SkinTemperature.sleep_date.desc())
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    return [
        {
            "sleep_date": str(r.sleep_date),
            "temperature_celsius": r.temperature_celsius,
            "deviation_from_baseline": r.deviation_from_baseline,
            "is_elevated": r.is_elevated,
        }
        for r in records
    ]


# ==============================================================================
# Export Endpoints (CSV/JSON)
# ==============================================================================


@get("/users/{user_id:str}/export/summary", status_code=HTTP_200_OK)
async def export_summary(
    user_id: str,
    session: AsyncSession,
    days: Annotated[int, Parameter(query="days", default=30, ge=1, le=365)] = 30,
) -> dict[str, Any]:
    """Export summary of all data for a user.

    Returns counts and date ranges for all data types.
    Useful for generating export manifests.
    """
    since_date = date.today() - timedelta(days=days)

    # Get counts for all data types
    from sqlalchemy import func

    from polar_flow_server.models.sleep import Sleep

    counts: dict[str, int] = {}

    # Sleep
    stmt = select(func.count(Sleep.id)).where(Sleep.user_id == user_id, Sleep.date >= since_date)
    counts["sleep"] = (await session.execute(stmt)).scalar() or 0

    # Activity
    stmt = select(func.count(Activity.id)).where(
        Activity.user_id == user_id, Activity.date >= since_date
    )
    counts["activity"] = (await session.execute(stmt)).scalar() or 0

    # Recharge
    stmt = select(func.count(NightlyRecharge.id)).where(
        NightlyRecharge.user_id == user_id, NightlyRecharge.date >= since_date
    )
    counts["recharge"] = (await session.execute(stmt)).scalar() or 0

    # Cardio Load
    stmt = select(func.count(CardioLoad.id)).where(
        CardioLoad.user_id == user_id, CardioLoad.date >= since_date
    )
    counts["cardio_load"] = (await session.execute(stmt)).scalar() or 0

    # Heart Rate
    stmt = select(func.count(ContinuousHeartRate.id)).where(
        ContinuousHeartRate.user_id == user_id, ContinuousHeartRate.date >= since_date
    )
    counts["heart_rate"] = (await session.execute(stmt)).scalar() or 0

    # Exercises
    stmt = select(func.count(Exercise.id)).where(
        Exercise.user_id == user_id, Exercise.start_time >= since_date
    )
    counts["exercises"] = (await session.execute(stmt)).scalar() or 0

    return {
        "user_id": user_id,
        "days": days,
        "from_date": str(since_date),
        "to_date": str(date.today()),
        "record_counts": counts,
        "total_records": sum(counts.values()),
    }


# Router with all endpoints
data_router = Router(
    path="/",
    route_handlers=[
        # Activity
        get_activity_list,
        get_activity_by_date,
        # Recharge
        get_recharge_list,
        # Cardio Load
        get_cardio_load_list,
        # Heart Rate
        get_heart_rate_list,
        # Exercises
        get_exercises_list,
        get_exercise_detail,
        # SleepWise
        get_alertness_list,
        get_bedtime_list,
        # Activity Samples
        get_activity_samples_list,
        # Biosensing
        get_spo2_list,
        get_ecg_list,
        get_body_temperature_list,
        get_skin_temperature_list,
        # Export
        export_summary,
    ],
)
