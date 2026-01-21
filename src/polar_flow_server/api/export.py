"""CSV Export API endpoints.

User-scoped data export endpoints for programmatic CSV downloads.
These endpoints are properly scoped to the authenticated user's data.
"""

import csv
import io
from datetime import date, timedelta
from typing import Annotated

from litestar import Router, get
from litestar.params import Parameter
from litestar.response import Response
from litestar.status_codes import HTTP_200_OK
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.core.auth import per_user_api_key_guard
from polar_flow_server.models.activity import Activity
from polar_flow_server.models.cardio_load import CardioLoad
from polar_flow_server.models.recharge import NightlyRecharge
from polar_flow_server.models.sleep import Sleep


@get(
    "/users/{user_id:str}/export/sleep.csv",
    status_code=HTTP_200_OK,
)
async def export_user_sleep_csv(
    user_id: str,
    session: AsyncSession,
    days: Annotated[int, Parameter(query="days", default=30, ge=1, le=365)] = 30,
) -> Response[bytes]:
    """Export sleep data as CSV for a specific user.

    Args:
        user_id: User identifier (Polar user ID)
        session: Database session (injected)
        days: Number of days to export (default: 30, max: 365)

    Returns:
        CSV file with sleep data

    Example:
        GET /api/v1/users/12345/export/sleep.csv?days=90
    """
    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(Sleep)
        .where(Sleep.user_id == user_id)
        .where(Sleep.date >= since_date)
        .order_by(Sleep.date.asc())
    )
    result = await session.execute(stmt)
    sleep_data = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "date",
            "sleep_score",
            "total_hours",
            "deep_hours",
            "light_hours",
            "rem_hours",
            "hrv_avg",
            "heart_rate_avg",
            "breathing_rate_avg",
        ]
    )

    for s in sleep_data:
        writer.writerow(
            [
                s.date.isoformat(),
                s.sleep_score or "",
                round(s.total_sleep_seconds / 3600, 2) if s.total_sleep_seconds else "",
                round(s.deep_sleep_seconds / 3600, 2) if s.deep_sleep_seconds else "",
                round(s.light_sleep_seconds / 3600, 2) if s.light_sleep_seconds else "",
                round(s.rem_sleep_seconds / 3600, 2) if s.rem_sleep_seconds else "",
                s.hrv_avg or "",
                s.heart_rate_avg or "",
                s.breathing_rate_avg or "",
            ]
        )

    return Response(
        content=output.getvalue().encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=sleep_{days}days.csv"},
    )


@get(
    "/users/{user_id:str}/export/activity.csv",
    status_code=HTTP_200_OK,
)
async def export_user_activity_csv(
    user_id: str,
    session: AsyncSession,
    days: Annotated[int, Parameter(query="days", default=30, ge=1, le=365)] = 30,
) -> Response[bytes]:
    """Export activity data as CSV for a specific user.

    Args:
        user_id: User identifier (Polar user ID)
        session: Database session (injected)
        days: Number of days to export (default: 30, max: 365)

    Returns:
        CSV file with activity data

    Example:
        GET /api/v1/users/12345/export/activity.csv?days=90
    """
    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(Activity)
        .where(Activity.user_id == user_id)
        .where(Activity.date >= since_date)
        .order_by(Activity.date.asc())
    )
    result = await session.execute(stmt)
    activity_data = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["date", "steps", "calories_active", "calories_total", "distance_km", "active_minutes"]
    )

    for a in activity_data:
        writer.writerow(
            [
                a.date.isoformat(),
                a.steps or "",
                a.calories_active or "",
                a.calories_total or "",
                round(a.distance_meters / 1000, 2) if a.distance_meters else "",
                round(a.active_time_seconds / 60, 1) if a.active_time_seconds else "",
            ]
        )

    return Response(
        content=output.getvalue().encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=activity_{days}days.csv"},
    )


@get(
    "/users/{user_id:str}/export/recharge.csv",
    status_code=HTTP_200_OK,
)
async def export_user_recharge_csv(
    user_id: str,
    session: AsyncSession,
    days: Annotated[int, Parameter(query="days", default=30, ge=1, le=365)] = 30,
) -> Response[bytes]:
    """Export nightly recharge (HRV) data as CSV for a specific user.

    Args:
        user_id: User identifier (Polar user ID)
        session: Database session (injected)
        days: Number of days to export (default: 30, max: 365)

    Returns:
        CSV file with recharge/HRV data

    Example:
        GET /api/v1/users/12345/export/recharge.csv?days=90
    """
    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(NightlyRecharge)
        .where(NightlyRecharge.user_id == user_id)
        .where(NightlyRecharge.date >= since_date)
        .order_by(NightlyRecharge.date.asc())
    )
    result = await session.execute(stmt)
    recharge_data = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "hrv_avg", "ans_charge", "status", "breathing_rate", "heart_rate_avg"])

    for r in recharge_data:
        writer.writerow(
            [
                r.date.isoformat(),
                r.hrv_avg or "",
                r.ans_charge or "",
                r.ans_charge_status or "",
                r.breathing_rate_avg or "",
                r.heart_rate_avg or "",
            ]
        )

    return Response(
        content=output.getvalue().encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=recharge_{days}days.csv"},
    )


@get(
    "/users/{user_id:str}/export/cardio-load.csv",
    status_code=HTTP_200_OK,
)
async def export_user_cardio_load_csv(
    user_id: str,
    session: AsyncSession,
    days: Annotated[int, Parameter(query="days", default=30, ge=1, le=365)] = 30,
) -> Response[bytes]:
    """Export cardio load data as CSV for a specific user.

    Args:
        user_id: User identifier (Polar user ID)
        session: Database session (injected)
        days: Number of days to export (default: 30, max: 365)

    Returns:
        CSV file with cardio load data

    Example:
        GET /api/v1/users/12345/export/cardio-load.csv?days=90
    """
    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(CardioLoad)
        .where(CardioLoad.user_id == user_id)
        .where(CardioLoad.date >= since_date)
        .order_by(CardioLoad.date.asc())
    )
    result = await session.execute(stmt)
    cardio_data = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "strain", "tolerance", "cardio_load", "load_ratio", "status"])

    for c in cardio_data:
        writer.writerow(
            [
                c.date.isoformat(),
                c.strain or "",
                c.tolerance or "",
                c.cardio_load or "",
                round(c.cardio_load_ratio, 2) if c.cardio_load_ratio else "",
                c.cardio_load_status or "",
            ]
        )

    return Response(
        content=output.getvalue().encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=cardio_load_{days}days.csv"},
    )


# Export router - protected by per-user API key authentication
export_router = Router(
    path="/",
    guards=[per_user_api_key_guard],
    route_handlers=[
        export_user_sleep_csv,
        export_user_activity_csv,
        export_user_recharge_csv,
        export_user_cardio_load_csv,
    ],
    tags=["Export"],
)
