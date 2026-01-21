"""Sync API endpoints."""

from typing import Annotated, Any

from litestar import Router, post
from litestar.params import Parameter
from litestar.status_codes import HTTP_200_OK
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.core.auth import per_user_api_key_guard
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
) -> dict[str, Any]:
    """Trigger data sync for a user.

    Args:
        user_id: User identifier (Polar user ID or Laravel UUID)
        session: Database session (injected)
        polar_token: Polar API access token (from header)
        days: Number of days to sync (optional, uses config default)

    Returns:
        Sync results with counts per data type and any errors

    Example:
        POST /api/v1/users/12345/sync/trigger?days=30
        Headers: X-Polar-Token: <access_token>
    """
    sync_service = SyncService(session)

    sync_result = await sync_service.sync_user(
        user_id=user_id,
        polar_token=polar_token,
        days=days,
    )

    return {
        "status": "partial" if sync_result.has_errors else "success",
        "user_id": user_id,
        "records": sync_result.records,
        "errors": sync_result.errors if sync_result.has_errors else None,
        "total_records": sync_result.total_records,
    }


sync_router = Router(
    path="/",
    guards=[per_user_api_key_guard],
    route_handlers=[trigger_sync],
)
