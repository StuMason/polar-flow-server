"""Sleep data API endpoints."""

from datetime import date, timedelta
from typing import Annotated

from litestar import Router, get
from litestar.openapi.spec import Example
from litestar.params import Parameter
from litestar.status_codes import HTTP_200_OK
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.core.auth import per_user_api_key_guard
from polar_flow_server.models.sleep import Sleep


@get(
    "/users/{user_id:str}/sleep",
    status_code=HTTP_200_OK,
)
async def get_sleep_list(
    user_id: str,
    session: AsyncSession,
    days: Annotated[int, Parameter(query="days", default=7, ge=1, le=365)] = 7,
) -> list[dict[str, str | int | float | None]]:
    """Get sleep data for a user.

    Args:
        user_id: User identifier (Polar user ID or Laravel UUID)
        session: Database session (injected)
        days: Number of days to fetch (default: 7)

    Returns:
        List of sleep records, ordered by date (most recent first)

    Example:
        GET /api/v1/users/12345/sleep?days=30
    """
    since_date = date.today() - timedelta(days=days)

    # Query sleep data for this user only
    stmt = (
        select(Sleep)
        .where(Sleep.user_id == user_id)
        .where(Sleep.date >= since_date)
        .order_by(Sleep.date.desc())
    )

    result = await session.execute(stmt)
    sleep_records = result.scalars().all()

    return [
        {
            "date": str(record.date),
            "sleep_score": record.sleep_score,
            "total_sleep_hours": (
                record.total_sleep_seconds / 3600 if record.total_sleep_seconds else None
            ),
            "light_sleep_hours": (
                record.light_sleep_seconds / 3600 if record.light_sleep_seconds else None
            ),
            "deep_sleep_hours": (
                record.deep_sleep_seconds / 3600 if record.deep_sleep_seconds else None
            ),
            "rem_sleep_hours": (
                record.rem_sleep_seconds / 3600 if record.rem_sleep_seconds else None
            ),
            "hrv_avg": record.hrv_avg,
            "heart_rate_avg": record.heart_rate_avg,
            "breathing_rate_avg": record.breathing_rate_avg,
            "skin_temperature_avg": record.skin_temperature_avg,
        }
        for record in sleep_records
    ]


@get(
    "/users/{user_id:str}/sleep/{sleep_date:str}",
    status_code=HTTP_200_OK,
)
async def get_sleep_by_date(
    user_id: str,
    sleep_date: Annotated[
        str,
        Parameter(
            description="Date to retrieve sleep data for (YYYY-MM-DD format)",
            pattern=r"^\d{4}-\d{2}-\d{2}$",
            examples=[
                Example(value="2026-01-20", summary="Today"),
                Example(value="2026-01-15", summary="Last week"),
            ],
        ),
    ],
    session: AsyncSession,
) -> dict[str, str | int | float | None] | None:
    """Get sleep data for a specific date.

    Args:
        user_id: User identifier
        sleep_date: Sleep date (YYYY-MM-DD)
        session: Database session (injected)

    Returns:
        Sleep record for the date, or None if not found

    Example:
        GET /api/v1/users/12345/sleep/2026-01-09
    """
    # Parse date
    target_date = date.fromisoformat(sleep_date)

    # Query for this user and date
    stmt = select(Sleep).where(
        Sleep.user_id == user_id,
        Sleep.date == target_date,
    )

    result = await session.execute(stmt)
    record = result.scalar_one_or_none()

    if not record:
        return None

    return {
        "date": str(record.date),
        "sleep_start_time": record.sleep_start_time,
        "sleep_end_time": record.sleep_end_time,
        "sleep_score": record.sleep_score,
        "sleep_rating": record.sleep_rating,
        "total_sleep_hours": (
            record.total_sleep_seconds / 3600 if record.total_sleep_seconds else None
        ),
        "light_sleep_hours": (
            record.light_sleep_seconds / 3600 if record.light_sleep_seconds else None
        ),
        "deep_sleep_hours": (
            record.deep_sleep_seconds / 3600 if record.deep_sleep_seconds else None
        ),
        "rem_sleep_hours": (record.rem_sleep_seconds / 3600 if record.rem_sleep_seconds else None),
        "interruptions_hours": (
            record.interruptions_seconds / 3600 if record.interruptions_seconds else None
        ),
        "hrv_avg": record.hrv_avg,
        "hrv_samples": record.hrv_samples,
        "heart_rate_avg": record.heart_rate_avg,
        "heart_rate_min": record.heart_rate_min,
        "heart_rate_max": record.heart_rate_max,
        "breathing_rate_avg": record.breathing_rate_avg,
        "skin_temperature_avg": record.skin_temperature_avg,
    }


sleep_router = Router(
    path="/",
    guards=[per_user_api_key_guard],
    route_handlers=[get_sleep_list, get_sleep_by_date],
    tags=["Sleep"],
)
