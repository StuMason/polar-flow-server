"""Sync API endpoints."""

from typing import Annotated

from litestar import Router, post
from litestar.params import Parameter
from litestar.status_codes import HTTP_200_OK
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.core.auth import api_key_guard
from polar_flow_server.services.sync import SyncService


@post(
    "/users/{user_id:str}/sync/trigger",
    status_code=HTTP_200_OK,
)
async def trigger_sync(
    user_id: str,
    session: AsyncSession,
    polar_token: Annotated[str, Parameter(header="X-Polar-Token")],
    days: Annotated[int | None, Parameter(query="days", ge=1, le=365)] = None,
) -> dict[str, str | dict[str, int]]:
    """Trigger data sync for a user.

    Args:
        user_id: User identifier (Polar user ID or Laravel UUID)
        session: Database session (injected)
        polar_token: Polar API access token (from header)
        days: Number of days to sync (optional, uses config default)

    Returns:
        Sync results with counts per data type

    Example:
        POST /api/v1/users/12345/sync/trigger?days=30
        Headers: X-Polar-Token: <access_token>
    """
    sync_service = SyncService(session)

    results = await sync_service.sync_user(
        user_id=user_id,
        polar_token=polar_token,
        days=days,
    )

    return {
        "status": "success",
        "user_id": user_id,
        "results": results,
    }


sync_router = Router(
    path="/",
    guards=[api_key_guard],
    route_handlers=[trigger_sync],
)
