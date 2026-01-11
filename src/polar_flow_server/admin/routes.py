"""Admin panel routes."""

import os
import secrets
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from litestar import Request, get, post
from litestar.response import Redirect, Template
from litestar.status_codes import HTTP_200_OK, HTTP_303_SEE_OTHER
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.core.config import settings
from polar_flow_server.core.security import token_encryption
from polar_flow_server.models.activity import Activity
from polar_flow_server.models.activity_samples import ActivitySamples
from polar_flow_server.models.cardio_load import CardioLoad
from polar_flow_server.models.continuous_hr import ContinuousHeartRate
from polar_flow_server.models.exercise import Exercise
from polar_flow_server.models.recharge import NightlyRecharge
from polar_flow_server.models.settings import AppSettings
from polar_flow_server.models.sleep import Sleep
from polar_flow_server.models.sleepwise_alertness import SleepWiseAlertness
from polar_flow_server.models.sleepwise_bedtime import SleepWiseBedtime
from polar_flow_server.models.user import User
from polar_flow_server.services.sync import SyncService

# In-memory OAuth state storage (for self-hosted single-instance use)
# In production SaaS, use Redis or database with TTL
_oauth_states: dict[str, datetime] = {}


@get("/", sync_to_thread=False)
async def admin_index(
    request: Request[Any, Any, Any], session: AsyncSession
) -> Template | Redirect:
    """Admin panel home - setup wizard or dashboard.

    Shows setup wizard if no app settings exist, otherwise dashboard.
    """
    # Check if app settings exist (indicates setup complete)
    stmt = select(AppSettings).where(AppSettings.id == 1)
    result = await session.execute(stmt)
    app_settings = result.scalar_one_or_none()

    if not app_settings:
        # No settings yet, show setup wizard
        return Template(template_name="admin/setup.html", context={})

    # Settings exist, show dashboard
    return Redirect(path="/admin/dashboard", status_code=HTTP_303_SEE_OTHER)


@post("/setup/oauth", sync_to_thread=False, status_code=HTTP_200_OK)
async def save_oauth_credentials(
    request: Request[Any, Any, Any],
    session: AsyncSession,
) -> Template:
    """Save Polar OAuth credentials to database."""
    form_data = await request.form()
    client_id = form_data.get("client_id")
    client_secret = form_data.get("client_secret")

    if not client_id or not client_secret:
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": "Both Client ID and Client Secret are required"},
        )

    try:
        # Encrypt client secret
        encrypted_secret = token_encryption.encrypt(client_secret)

        # Create or update app settings
        stmt = select(AppSettings).where(AppSettings.id == 1)
        result = await session.execute(stmt)
        app_settings = result.scalar_one_or_none()

        if app_settings:
            # Update existing
            app_settings.polar_client_id = client_id
            app_settings.polar_client_secret_encrypted = encrypted_secret
        else:
            # Create new
            app_settings = AppSettings(
                id=1,
                polar_client_id=client_id,
                polar_client_secret_encrypted=encrypted_secret,
            )
            session.add(app_settings)

        await session.commit()

        return Template(template_name="admin/partials/setup_success.html", context={})

    except Exception as e:
        await session.rollback()
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": f"Failed to save credentials: {str(e)}"},
        )


@get("/dashboard", sync_to_thread=False)
async def admin_dashboard(request: Request[Any, Any, Any], session: AsyncSession) -> Template:
    """Admin dashboard with stats and sync controls."""
    # Get data counts for all endpoints
    sleep_count = (await session.execute(select(func.count(Sleep.id)))).scalar() or 0
    exercise_count = (await session.execute(select(func.count(Exercise.id)))).scalar() or 0
    activity_count = (await session.execute(select(func.count(Activity.id)))).scalar() or 0
    recharge_count = (await session.execute(select(func.count(NightlyRecharge.id)))).scalar() or 0
    cardio_load_count = (await session.execute(select(func.count(CardioLoad.id)))).scalar() or 0
    alertness_count = (
        await session.execute(select(func.count(SleepWiseAlertness.id)))
    ).scalar() or 0
    bedtime_count = (await session.execute(select(func.count(SleepWiseBedtime.id)))).scalar() or 0
    activity_samples_count = (
        await session.execute(select(func.count(ActivitySamples.id)))
    ).scalar() or 0
    continuous_hr_count = (
        await session.execute(select(func.count(ContinuousHeartRate.id)))
    ).scalar() or 0

    # Get latest sleep data (last 7 days)
    since_date = date.today() - timedelta(days=7)
    recent_sleep_stmt = (
        select(Sleep).where(Sleep.date >= since_date).order_by(Sleep.date.desc()).limit(7)
    )
    result = await session.execute(recent_sleep_stmt)
    recent_sleep = result.scalars().all()

    # Get latest HRV from Nightly Recharge (not Sleep - Sleep API doesn't return HRV)
    latest_hrv = None
    latest_recharge_stmt = (
        select(NightlyRecharge)
        .where(NightlyRecharge.hrv_avg.isnot(None))
        .order_by(NightlyRecharge.date.desc())
        .limit(1)
    )
    recharge_result = await session.execute(latest_recharge_stmt)
    latest_recharge = recharge_result.scalar_one_or_none()
    if latest_recharge:
        latest_hrv = latest_recharge.hrv_avg

    # Get latest cardio load
    latest_cardio_stmt = select(CardioLoad).order_by(CardioLoad.date.desc()).limit(1)
    cardio_result = await session.execute(latest_cardio_stmt)
    latest_cardio = cardio_result.scalar_one_or_none()

    # Get latest continuous HR
    latest_hr_stmt = select(ContinuousHeartRate).order_by(ContinuousHeartRate.date.desc()).limit(1)
    hr_result = await session.execute(latest_hr_stmt)
    latest_hr = hr_result.scalar_one_or_none()

    # Get latest alertness
    latest_alertness_stmt = (
        select(SleepWiseAlertness).order_by(SleepWiseAlertness.period_start_time.desc()).limit(1)
    )
    alertness_result = await session.execute(latest_alertness_stmt)
    latest_alertness = alertness_result.scalar_one_or_none()

    # Get recent recharge data (last 7 days)
    recent_recharge_stmt = (
        select(NightlyRecharge)
        .where(NightlyRecharge.date >= since_date)
        .order_by(NightlyRecharge.date.desc())
        .limit(7)
    )
    recharge_list_result = await session.execute(recent_recharge_stmt)
    recent_recharge = recharge_list_result.scalars().all()

    return Template(
        template_name="admin/dashboard.html",
        context={
            "sleep_count": sleep_count,
            "exercise_count": exercise_count,
            "activity_count": activity_count,
            "recharge_count": recharge_count,
            "cardio_load_count": cardio_load_count,
            "alertness_count": alertness_count,
            "bedtime_count": bedtime_count,
            "activity_samples_count": activity_samples_count,
            "continuous_hr_count": continuous_hr_count,
            "recent_sleep": recent_sleep,
            "recent_recharge": recent_recharge,
            "latest_hrv": latest_hrv,
            "latest_cardio": latest_cardio,
            "latest_hr": latest_hr,
            "latest_alertness": latest_alertness,
            "sync_interval_hours": settings.sync_interval_hours,
        },
    )


@post("/sync", sync_to_thread=False, status_code=HTTP_200_OK)
async def trigger_manual_sync(request: Request[Any, Any, Any], session: AsyncSession) -> Template:
    """Trigger manual sync and return updated stats."""
    # Get user and token from database
    stmt = select(User).where(User.is_active == True).limit(1)  # noqa: E712
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    # Get token - from user if exists, otherwise fall back to env var (testing only)
    user_id: str
    polar_token: str

    if user:
        user_id = user.polar_user_id
        polar_token = token_encryption.decrypt(user.access_token_encrypted)
    else:
        # Testing fallback - check env var directly
        env_token = os.getenv("ACCESS_TOKEN")
        if not env_token:
            return Template(
                template_name="admin/partials/sync_error.html",
                context={
                    "error": "No user configured. Complete setup first or set ACCESS_TOKEN env var for testing."
                },
            )
        polar_token = env_token
        user_id = "self"

    # Run sync
    sync_service = SyncService(session)
    try:
        results = await sync_service.sync_user(
            user_id=user_id,
            polar_token=polar_token,
            days=settings.sync_days_lookback,
        )

        # Get updated counts
        sleep_count = (await session.execute(select(func.count(Sleep.id)))).scalar() or 0
        exercise_count = (await session.execute(select(func.count(Exercise.id)))).scalar() or 0
        activity_count = (await session.execute(select(func.count(Activity.id)))).scalar() or 0

        return Template(
            template_name="admin/partials/sync_success.html",
            context={
                "results": results,
                "sleep_count": sleep_count,
                "exercise_count": exercise_count,
                "activity_count": activity_count,
            },
        )
    except Exception as e:
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": str(e)},
        )


@get("/oauth/authorize", sync_to_thread=False)
async def oauth_authorize(session: AsyncSession) -> Redirect:
    """Start OAuth flow - redirect to Polar authorization page."""
    # Get OAuth credentials from database
    stmt = select(AppSettings).where(AppSettings.id == 1)
    result = await session.execute(stmt)
    app_settings = result.scalar_one_or_none()

    if not app_settings or not app_settings.polar_client_id:
        # No OAuth credentials configured, redirect to setup
        return Redirect(path="/admin", status_code=HTTP_303_SEE_OTHER)

    # Generate CSRF state token
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = datetime.utcnow() + timedelta(minutes=10)

    # Clean up expired states
    now = datetime.utcnow()
    expired = [s for s, exp in _oauth_states.items() if exp < now]
    for s in expired:
        del _oauth_states[s]

    # Build authorization URL with state for CSRF protection
    params = {
        "client_id": app_settings.polar_client_id,
        "response_type": "code",
        "redirect_uri": "http://localhost:8000/admin/oauth/callback",
        "state": state,
    }
    auth_url = f"https://flow.polar.com/oauth2/authorization?{urlencode(params)}"

    return Redirect(path=auth_url, status_code=HTTP_303_SEE_OTHER)


@get("/oauth/callback", sync_to_thread=False)
async def oauth_callback(
    request: Request[Any, Any, Any], session: AsyncSession
) -> Redirect | Template:
    """Handle OAuth callback from Polar."""
    # Get authorization code and state from query params
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error or not code:
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": f"OAuth authorization failed: {error or 'No code received'}"},
        )

    # Validate CSRF state token
    if not state or state not in _oauth_states:
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": "Invalid OAuth state - possible CSRF attack. Please try again."},
        )

    # Check state hasn't expired and remove it (one-time use)
    if _oauth_states[state] < datetime.utcnow():
        del _oauth_states[state]
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": "OAuth state expired. Please try again."},
        )
    del _oauth_states[state]

    # Get OAuth credentials from database
    stmt = select(AppSettings).where(AppSettings.id == 1)
    result = await session.execute(stmt)
    app_settings = result.scalar_one_or_none()

    if (
        not app_settings
        or not app_settings.polar_client_id
        or not app_settings.polar_client_secret_encrypted
    ):
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": "OAuth credentials not configured"},
        )

    # Exchange code for access token
    client_secret = token_encryption.decrypt(app_settings.polar_client_secret_encrypted)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://polarremote.com/v2/oauth2/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": "http://localhost:8000/admin/oauth/callback",
                },
                auth=(app_settings.polar_client_id, client_secret),
            )
            response.raise_for_status()
            token_data = response.json()

        # Polar includes user_id in the token response as x_user_id
        x_user_id = token_data.get("x_user_id")
        if x_user_id is None:
            return Template(
                template_name="admin/partials/sync_error.html",
                context={"error": "OAuth response missing user ID (x_user_id)"},
            )
        polar_user_id = str(x_user_id)
        access_token_encrypted = token_encryption.encrypt(token_data["access_token"])

        # Calculate token expiry
        expires_in = token_data.get("expires_in", 31536000)  # Default 1 year
        token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        # Check if user exists
        user_stmt = select(User).where(User.polar_user_id == polar_user_id)
        user_result = await session.execute(user_stmt)
        existing_user = user_result.scalar_one_or_none()

        if existing_user:
            # Update existing user
            existing_user.access_token_encrypted = access_token_encrypted
            existing_user.token_expires_at = token_expires_at
            existing_user.is_active = True
        else:
            # Create new user
            new_user = User(
                polar_user_id=polar_user_id,
                access_token_encrypted=access_token_encrypted,
                token_expires_at=token_expires_at,
                is_active=True,
            )
            session.add(new_user)

        await session.commit()

        # Redirect to dashboard
        return Redirect(path="/admin/dashboard", status_code=HTTP_303_SEE_OTHER)

    except Exception as e:
        await session.rollback()
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": f"Failed to complete OAuth flow: {str(e)}"},
        )


@get("/settings", sync_to_thread=False)
async def admin_settings(request: Request[Any, Any, Any], session: AsyncSession) -> Template:
    """Admin settings page - view/edit OAuth credentials and connection status."""
    # Get app settings
    stmt = select(AppSettings).where(AppSettings.id == 1)
    result = await session.execute(stmt)
    app_settings = result.scalar_one_or_none()

    # Get connected user
    user_stmt = select(User).where(User.is_active == True).limit(1)  # noqa: E712
    user_result = await session.execute(user_stmt)
    connected_user = user_result.scalar_one_or_none()

    return Template(
        template_name="admin/settings.html",
        context={
            "has_credentials": bool(app_settings and app_settings.polar_client_id),
            "client_id": app_settings.polar_client_id if app_settings else None,
            "connected_user": connected_user,
        },
    )


# Export routes
admin_routes = [
    admin_index,
    save_oauth_credentials,
    admin_dashboard,
    trigger_manual_sync,
    oauth_authorize,
    oauth_callback,
    admin_settings,
]
