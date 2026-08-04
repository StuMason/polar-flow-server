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
from typing import Annotated, Any

from pydantic import Field
from sqlalchemy import select

from polar_flow_server.mcp_server.context import resolve_scoped_user_id
from polar_flow_server.models.cardio_load import CardioLoad
from polar_flow_server.models.recharge import NightlyRecharge
from polar_flow_server.models.sleep import Sleep

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


def _hours(seconds: int | None) -> float | None:
    """Convert a seconds count to hours rounded to 2 decimals."""
    return round(seconds / 3600, 2) if seconds else None
