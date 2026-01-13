"""Admin panel routes."""

import csv
import io
import os
import re
import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from litestar import Request, get, post
from litestar.response import Redirect, Response, Template
from litestar.status_codes import HTTP_200_OK, HTTP_303_SEE_OTHER
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.admin.auth import (
    admin_user_exists,
    authenticate_admin,
    create_admin_user,
    is_authenticated,
    login_admin,
    logout_admin,
)
from polar_flow_server.core.config import settings
from polar_flow_server.core.security import token_encryption
from polar_flow_server.models.activity import Activity
from polar_flow_server.models.activity_samples import ActivitySamples
from polar_flow_server.models.api_key import APIKey
from polar_flow_server.models.baseline import UserBaseline
from polar_flow_server.models.cardio_load import CardioLoad
from polar_flow_server.models.continuous_hr import ContinuousHeartRate
from polar_flow_server.models.ecg import ECG
from polar_flow_server.models.exercise import Exercise
from polar_flow_server.models.pattern import PatternAnalysis
from polar_flow_server.models.recharge import NightlyRecharge
from polar_flow_server.models.settings import AppSettings
from polar_flow_server.models.sleep import Sleep
from polar_flow_server.models.sleepwise_alertness import SleepWiseAlertness
from polar_flow_server.models.sleepwise_bedtime import SleepWiseBedtime
from polar_flow_server.models.spo2 import SpO2
from polar_flow_server.models.sync_log import SyncLog
from polar_flow_server.models.temperature import BodyTemperature, SkinTemperature
from polar_flow_server.models.user import User
from polar_flow_server.services.scheduler import get_scheduler
from polar_flow_server.services.sync import SyncService

# In-memory OAuth state storage (for self-hosted single-instance use)
# In production SaaS, use Redis or database with TTL
_oauth_states: dict[str, datetime] = {}

# Simple email validation pattern
_EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def _get_csrf_token(request: Request[Any, Any, Any]) -> str | None:
    """Get CSRF token for template forms.

    The CSRF middleware stores the token in the csrf_token cookie.
    We read it from there to pass to templates for form submission.
    """
    return request.cookies.get("csrf_token")


def _get_base_url(request: Request[Any, Any, Any]) -> str:
    """Get the base URL for OAuth callbacks.

    Priority:
    1. BASE_URL environment variable (production)
    2. Auto-detect from request headers (development)
    """
    if settings.base_url:
        return settings.base_url.rstrip("/")

    # Auto-detect from request
    # Check for proxy headers first (common in production)
    proto = request.headers.get("X-Forwarded-Proto", "http")
    host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host", "localhost:8000")

    return f"{proto}://{host}"


def _calculate_recovery_status(
    sleep: Sleep | None,
    recharge: NightlyRecharge | None,
    cardio: CardioLoad | None,
) -> dict[str, Any]:
    """Calculate recovery status and generate recommendations.

    Returns a dict with:
    - readiness: "excellent" | "good" | "fair" | "poor"
    - readiness_score: 0-100
    - recommendations: list of actionable advice
    - training_advice: what type of training is appropriate today
    """
    recommendations: list[str] = []
    factors: list[float] = []

    # Sleep factor (0-100)
    sleep_score = 50  # default if no data
    if sleep and sleep.sleep_score:
        sleep_score = sleep.sleep_score
        if sleep_score >= 85:
            recommendations.append("Excellent sleep! You're well-rested for intense training.")
        elif sleep_score >= 70:
            pass  # good, no recommendation needed
        elif sleep_score >= 50:
            recommendations.append("Sleep was fair. Consider a lighter workout today.")
        else:
            recommendations.append("Poor sleep. Prioritize recovery over training.")
        factors.append(sleep_score)

    # HRV/ANS factor (0-100)
    ans_score: float = 50.0  # default
    if recharge:
        if recharge.ans_charge:
            ans_score = float(recharge.ans_charge)
            if ans_score >= 70:
                recommendations.append("ANS recovery is excellent. Your body is ready for stress.")
            elif ans_score >= 50:
                pass  # normal
            elif ans_score >= 30:
                recommendations.append("ANS recovery is moderate. Keep intensity manageable.")
            else:
                recommendations.append("ANS shows fatigue. Focus on active recovery today.")
            factors.append(ans_score)

        # Check HRV trend if available
        if recharge.hrv_avg:
            # Note: In a real app, we'd compare to baseline
            if recharge.hrv_avg < 25:
                recommendations.append("Low HRV detected. Your body may be under stress.")

    # Training load factor
    load_score = 50  # default balanced
    if cardio and cardio.cardio_load_ratio:
        ratio = cardio.cardio_load_ratio
        if ratio >= 1.5:
            load_score = 20
            recommendations.append("High training load! Take a recovery day to avoid overtraining.")
        elif ratio >= 1.2:
            load_score = 40
            recommendations.append("Training load elevated. Consider reducing intensity.")
        elif ratio >= 0.8:
            load_score = 80
            # Good balance, no recommendation
        elif ratio >= 0.5:
            load_score = 60
            recommendations.append("Training load is low. You can push harder if you feel good.")
        else:
            load_score = 40
            recommendations.append(
                "Very low training load. Consider increasing activity to maintain fitness."
            )
        factors.append(load_score)

    # Calculate overall readiness
    if factors:
        readiness_score = sum(factors) / len(factors)
    else:
        readiness_score = 50  # no data

    # Determine readiness level
    if readiness_score >= 80:
        readiness = "excellent"
        training_advice = "Great day for high-intensity training, intervals, or competition."
    elif readiness_score >= 65:
        readiness = "good"
        training_advice = (
            "Good for moderate training. Tempo runs, strength work, or steady-state cardio."
        )
    elif readiness_score >= 45:
        readiness = "fair"
        training_advice = "Best for easy training. Light jog, mobility work, or skill practice."
    else:
        readiness = "poor"
        training_advice = "Recovery day recommended. Gentle stretching, walking, or complete rest."

    # Add training advice as recommendation
    if not recommendations:
        recommendations.append("All metrics look normal. Train as planned!")

    return {
        "readiness": readiness,
        "readiness_score": round(readiness_score),
        "recommendations": recommendations,
        "training_advice": training_advice,
        "has_data": bool(factors),
    }


@get("/", sync_to_thread=False)
async def admin_index(
    request: Request[Any, Any, Any], session: AsyncSession
) -> Template | Redirect:
    """Admin panel home - handles initial setup flow.

    Flow:
    1. No admin user exists → /admin/setup/account (create first admin)
    2. Not logged in → /admin/login
    3. No OAuth settings → /admin/setup (OAuth setup)
    4. All good → /admin/dashboard
    """
    # Step 1: Check if admin user exists
    if not await admin_user_exists(session):
        return Redirect(path="/admin/setup/account", status_code=HTTP_303_SEE_OTHER)

    # Step 2: Check if authenticated
    if not is_authenticated(request):
        return Redirect(path="/admin/login", status_code=HTTP_303_SEE_OTHER)

    # Step 3: Check if OAuth settings exist
    stmt = select(AppSettings).where(AppSettings.id == 1)
    result = await session.execute(stmt)
    app_settings = result.scalar_one_or_none()

    if not app_settings or not app_settings.polar_client_id:
        # No OAuth settings yet, show setup wizard
        base_url = _get_base_url(request)
        return Template(
            template_name="admin/setup.html",
            context={
                "callback_url": f"{base_url}/admin/oauth/callback",
                "csrf_token": _get_csrf_token(request),
            },
        )

    # All good, go to dashboard
    return Redirect(path="/admin/dashboard", status_code=HTTP_303_SEE_OTHER)


# =============================================================================
# Admin Account Setup (First-Run)
# =============================================================================


@get("/setup/account", sync_to_thread=False)
async def setup_account_form(
    request: Request[Any, Any, Any], session: AsyncSession
) -> Template | Redirect:
    """Show admin account creation form.

    Only accessible if no admin user exists yet.
    """
    if await admin_user_exists(session):
        return Redirect(path="/admin", status_code=HTTP_303_SEE_OTHER)

    return Template(
        template_name="admin/setup_account.html",
        context={"csrf_token": _get_csrf_token(request)},
    )


@post("/setup/account", sync_to_thread=False)
async def setup_account_submit(
    request: Request[Any, Any, Any], session: AsyncSession
) -> Template | Redirect:
    """Create the first admin account.

    Only accessible if no admin user exists yet.
    """
    if await admin_user_exists(session):
        return Redirect(path="/admin", status_code=HTTP_303_SEE_OTHER)

    form_data = await request.form()
    email = form_data.get("email", "").strip()
    password = form_data.get("password", "")
    password_confirm = form_data.get("password_confirm", "")
    name = form_data.get("name", "").strip() or None

    # Validation
    errors = []
    if not email:
        errors.append("Email is required")
    elif not _EMAIL_PATTERN.match(email):
        errors.append("Invalid email address")

    if not password:
        errors.append("Password is required")
    elif len(password) < 8:
        errors.append("Password must be at least 8 characters")

    if password != password_confirm:
        errors.append("Passwords do not match")

    if errors:
        return Template(
            template_name="admin/setup_account.html",
            context={
                "errors": errors,
                "email": email,
                "name": name,
                "csrf_token": _get_csrf_token(request),
            },
        )

    # Create admin user
    try:
        admin = await create_admin_user(
            email=str(email),
            password=str(password),
            session=session,
            name=str(name) if name else None,
        )
        # Log them in immediately
        login_admin(request, admin)
        return Redirect(path="/admin", status_code=HTTP_303_SEE_OTHER)
    except Exception as e:
        return Template(
            template_name="admin/setup_account.html",
            context={
                "errors": [str(e)],
                "email": email,
                "name": name,
                "csrf_token": _get_csrf_token(request),
            },
        )


# =============================================================================
# Login / Logout
# =============================================================================


@get("/login", sync_to_thread=False)
async def login_form(request: Request[Any, Any, Any], session: AsyncSession) -> Template | Redirect:
    """Show login form.

    Redirects to setup if no admin exists, or to dashboard if already logged in.
    """
    if not await admin_user_exists(session):
        return Redirect(path="/admin/setup/account", status_code=HTTP_303_SEE_OTHER)

    if is_authenticated(request):
        return Redirect(path="/admin", status_code=HTTP_303_SEE_OTHER)

    return Template(
        template_name="admin/login.html",
        context={"csrf_token": _get_csrf_token(request)},
    )


@post("/login", sync_to_thread=False)
async def login_submit(
    request: Request[Any, Any, Any], session: AsyncSession
) -> Template | Redirect:
    """Process login form submission."""
    form_data = await request.form()
    email = form_data.get("email", "").strip()
    password = form_data.get("password", "")

    if not email or not password:
        return Template(
            template_name="admin/login.html",
            context={
                "error": "Email and password are required",
                "email": email,
                "csrf_token": _get_csrf_token(request),
            },
        )

    admin = await authenticate_admin(str(email), str(password), session)
    if not admin:
        return Template(
            template_name="admin/login.html",
            context={
                "error": "Invalid credentials",
                "email": email,
                "csrf_token": _get_csrf_token(request),
            },
        )

    login_admin(request, admin)
    return Redirect(path="/admin", status_code=HTTP_303_SEE_OTHER)


@post("/logout", sync_to_thread=False)
async def logout(request: Request[Any, Any, Any]) -> Redirect:
    """Log out and redirect to login page."""
    logout_admin(request)
    return Redirect(path="/admin/login", status_code=HTTP_303_SEE_OTHER)


@post("/setup/oauth", sync_to_thread=False, status_code=HTTP_200_OK)
async def save_oauth_credentials(
    request: Request[Any, Any, Any],
    session: AsyncSession,
) -> Template:
    """Save Polar OAuth credentials to database."""
    # Auth check
    if not is_authenticated(request):
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": "Authentication required. Please log in."},
        )

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
async def admin_dashboard(
    request: Request[Any, Any, Any], session: AsyncSession
) -> Template | Redirect:
    """Admin dashboard with stats and sync controls."""
    # Auth check - redirect to login if not authenticated
    if not is_authenticated(request):
        return Redirect(path="/admin/login", status_code=HTTP_303_SEE_OTHER)

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

    # Biosensing counts (v1.4.0)
    spo2_count = (await session.execute(select(func.count(SpO2.id)))).scalar() or 0
    ecg_count = (await session.execute(select(func.count(ECG.id)))).scalar() or 0
    body_temp_count = (
        await session.execute(select(func.count(BodyTemperature.id)))
    ).scalar() or 0
    skin_temp_count = (
        await session.execute(select(func.count(SkinTemperature.id)))
    ).scalar() or 0

    # Analytics counts
    baseline_count = (await session.execute(select(func.count(UserBaseline.id)))).scalar() or 0
    pattern_count = (await session.execute(select(func.count(PatternAnalysis.id)))).scalar() or 0

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

    # Get latest SpO2
    latest_spo2_stmt = select(SpO2).order_by(SpO2.test_time.desc()).limit(1)
    spo2_result = await session.execute(latest_spo2_stmt)
    latest_spo2 = spo2_result.scalar_one_or_none()

    # Get latest skin temperature (night-time, has baseline deviation)
    latest_skin_temp_stmt = select(SkinTemperature).order_by(SkinTemperature.sleep_date.desc()).limit(1)
    skin_temp_result = await session.execute(latest_skin_temp_stmt)
    latest_skin_temp = skin_temp_result.scalar_one_or_none()

    # Get recent recharge data (last 7 days)
    recent_recharge_stmt = (
        select(NightlyRecharge)
        .where(NightlyRecharge.date >= since_date)
        .order_by(NightlyRecharge.date.desc())
        .limit(7)
    )
    recharge_list_result = await session.execute(recent_recharge_stmt)
    recent_recharge = recharge_list_result.scalars().all()

    # Calculate recovery recommendations
    recovery_status = _calculate_recovery_status(
        sleep=recent_sleep[0] if recent_sleep else None,
        recharge=latest_recharge,
        cardio=latest_cardio,
    )

    # Get API keys data
    api_keys_stmt = select(APIKey).order_by(APIKey.created_at.desc())
    api_keys_result = await session.execute(api_keys_stmt)
    api_keys = api_keys_result.scalars().all()

    # Get scheduler status
    scheduler = get_scheduler()
    scheduler_status = scheduler.get_status() if scheduler else {
        "enabled": settings.sync_enabled,
        "is_running": False,
        "interval_minutes": settings.sync_interval_minutes,
        "next_run_at": None,
        "last_run_at": None,
        "last_run_stats": None,
    }

    # Get recent sync logs
    sync_logs_stmt = select(SyncLog).order_by(SyncLog.started_at.desc()).limit(10)
    sync_logs_result = await session.execute(sync_logs_stmt)
    recent_sync_logs = sync_logs_result.scalars().all()

    # Calculate sync stats
    last_24h = datetime.now(UTC) - timedelta(hours=24)
    sync_stats_stmt = select(SyncLog).where(SyncLog.started_at >= last_24h)
    sync_stats_result = await session.execute(sync_stats_stmt)
    recent_syncs = sync_stats_result.scalars().all()

    sync_stats = {
        "total_24h": len(recent_syncs),
        "successful_24h": sum(1 for s in recent_syncs if s.status == "success"),
        "failed_24h": sum(1 for s in recent_syncs if s.status == "failed"),
        "partial_24h": sum(1 for s in recent_syncs if s.status == "partial"),
    }

    return Template(
        template_name="admin/dashboard.html",
        context={
            # Core data counts
            "sleep_count": sleep_count,
            "exercise_count": exercise_count,
            "activity_count": activity_count,
            "recharge_count": recharge_count,
            "cardio_load_count": cardio_load_count,
            "alertness_count": alertness_count,
            "bedtime_count": bedtime_count,
            "activity_samples_count": activity_samples_count,
            "continuous_hr_count": continuous_hr_count,
            # Biosensing counts
            "spo2_count": spo2_count,
            "ecg_count": ecg_count,
            "body_temp_count": body_temp_count,
            "skin_temp_count": skin_temp_count,
            # Analytics counts
            "baseline_count": baseline_count,
            "pattern_count": pattern_count,
            # Latest data
            "recent_sleep": recent_sleep,
            "recent_recharge": recent_recharge,
            "latest_hrv": latest_hrv,
            "latest_cardio": latest_cardio,
            "latest_hr": latest_hr,
            "latest_alertness": latest_alertness,
            "latest_spo2": latest_spo2,
            "latest_skin_temp": latest_skin_temp,
            # Recovery
            "recovery_status": recovery_status,
            # API keys
            "api_keys": api_keys,
            # Sync scheduler
            "sync_interval_minutes": settings.sync_interval_minutes,
            "scheduler_status": scheduler_status,
            "recent_sync_logs": recent_sync_logs,
            "sync_stats": sync_stats,
            # CSRF
            "csrf_token": _get_csrf_token(request),
        },
    )


@post("/sync", sync_to_thread=False, status_code=HTTP_200_OK)
async def trigger_manual_sync(request: Request[Any, Any, Any], session: AsyncSession) -> Template:
    """Trigger manual sync and return updated stats."""
    # Auth check
    if not is_authenticated(request):
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": "Authentication required. Please log in."},
        )

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
async def oauth_authorize(request: Request[Any, Any, Any], session: AsyncSession) -> Redirect:
    """Start OAuth flow - redirect to Polar authorization page."""
    # Auth check
    if not is_authenticated(request):
        return Redirect(path="/admin/login", status_code=HTTP_303_SEE_OTHER)

    # Get OAuth credentials from database
    stmt = select(AppSettings).where(AppSettings.id == 1)
    result = await session.execute(stmt)
    app_settings = result.scalar_one_or_none()

    if not app_settings or not app_settings.polar_client_id:
        # No OAuth credentials configured, redirect to setup
        return Redirect(path="/admin", status_code=HTTP_303_SEE_OTHER)

    # Generate CSRF state token
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = datetime.now(UTC) + timedelta(minutes=10)

    # Clean up expired states
    now = datetime.now(UTC)
    expired = [s for s, exp in _oauth_states.items() if exp < now]
    for s in expired:
        del _oauth_states[s]

    # Build authorization URL with state for CSRF protection
    base_url = _get_base_url(request)
    redirect_uri = f"{base_url}/admin/oauth/callback"

    params = {
        "client_id": app_settings.polar_client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
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
    if _oauth_states[state] < datetime.now(UTC):
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

    # Use same redirect_uri as authorization request
    base_url = _get_base_url(request)
    redirect_uri = f"{base_url}/admin/oauth/callback"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://polarremote.com/v2/oauth2/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
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
        token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

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
async def admin_settings(
    request: Request[Any, Any, Any], session: AsyncSession
) -> Template | Redirect:
    """Admin settings page - view/edit OAuth credentials and connection status."""
    # Auth check
    if not is_authenticated(request):
        return Redirect(path="/admin/login", status_code=HTTP_303_SEE_OTHER)

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


@post("/settings/reset-oauth", sync_to_thread=False, status_code=HTTP_200_OK)
async def reset_oauth_credentials(
    request: Request[Any, Any, Any],
    session: AsyncSession,
) -> Template:
    """Reset OAuth credentials - clears client ID and secret from database."""
    # Auth check
    if not is_authenticated(request):
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": "Authentication required. Please log in."},
        )

    try:
        # Get app settings and clear OAuth credentials
        stmt = select(AppSettings).where(AppSettings.id == 1)
        result = await session.execute(stmt)
        app_settings = result.scalar_one_or_none()

        if app_settings:
            app_settings.polar_client_id = None
            app_settings.polar_client_secret_encrypted = None
            await session.commit()

        # Return the "no credentials" state HTML
        return Template(
            template_name="admin/partials/oauth_reset_success.html",
            context={},
        )

    except Exception as e:
        await session.rollback()
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": f"Failed to reset credentials: {str(e)}"},
        )


# ============================================================================
# Chart Data API Routes (JSON endpoints for Chart.js)
# ============================================================================


@get("/api/charts/sleep", sync_to_thread=False)
async def chart_sleep_data(
    request: Request[Any, Any, Any],
    session: AsyncSession,
    days: int = 30,
) -> dict[str, Any]:
    """Get sleep data for charts.

    Returns sleep score, duration, and stage breakdown for the last N days.
    """
    if not is_authenticated(request):
        return {"error": "Authentication required", "status": 401}

    since_date = date.today() - timedelta(days=days)
    stmt = select(Sleep).where(Sleep.date >= since_date).order_by(Sleep.date.asc())
    result = await session.execute(stmt)
    sleep_data = result.scalars().all()

    return {
        "labels": [s.date.isoformat() for s in sleep_data],
        "datasets": {
            "sleep_score": [s.sleep_score for s in sleep_data],
            "total_hours": [
                round(s.total_sleep_seconds / 3600, 2) if s.total_sleep_seconds else 0
                for s in sleep_data
            ],
            "deep_hours": [
                round(s.deep_sleep_seconds / 3600, 2) if s.deep_sleep_seconds else 0
                for s in sleep_data
            ],
            "light_hours": [
                round(s.light_sleep_seconds / 3600, 2) if s.light_sleep_seconds else 0
                for s in sleep_data
            ],
            "rem_hours": [
                round(s.rem_sleep_seconds / 3600, 2) if s.rem_sleep_seconds else 0
                for s in sleep_data
            ],
        },
    }


@get("/api/charts/activity", sync_to_thread=False)
async def chart_activity_data(
    request: Request[Any, Any, Any],
    session: AsyncSession,
    days: int = 30,
) -> dict[str, Any]:
    """Get activity data for charts.

    Returns steps, calories, and active time for the last N days.
    """
    if not is_authenticated(request):
        return {"error": "Authentication required", "status": 401}

    since_date = date.today() - timedelta(days=days)
    stmt = select(Activity).where(Activity.date >= since_date).order_by(Activity.date.asc())
    result = await session.execute(stmt)
    activity_data = result.scalars().all()

    return {
        "labels": [a.date.isoformat() for a in activity_data],
        "datasets": {
            "steps": [a.steps or 0 for a in activity_data],
            "calories_active": [a.calories_active or 0 for a in activity_data],
            "calories_total": [a.calories_total or 0 for a in activity_data],
            "active_minutes": [
                round(a.active_time_seconds / 60, 1) if a.active_time_seconds else 0
                for a in activity_data
            ],
            "distance_km": [
                round(a.distance_meters / 1000, 2) if a.distance_meters else 0
                for a in activity_data
            ],
        },
    }


@get("/api/charts/heart-rate", sync_to_thread=False)
async def chart_heart_rate_data(
    request: Request[Any, Any, Any],
    session: AsyncSession,
    days: int = 30,
) -> dict[str, Any]:
    """Get heart rate data for charts.

    Returns min/avg/max heart rate for the last N days.
    """
    if not is_authenticated(request):
        return {"error": "Authentication required", "status": 401}

    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(ContinuousHeartRate)
        .where(ContinuousHeartRate.date >= since_date)
        .order_by(ContinuousHeartRate.date.asc())
    )
    result = await session.execute(stmt)
    hr_data = result.scalars().all()

    return {
        "labels": [h.date.isoformat() for h in hr_data],
        "datasets": {
            "hr_min": [h.hr_min or 0 for h in hr_data],
            "hr_avg": [h.hr_avg or 0 for h in hr_data],
            "hr_max": [h.hr_max or 0 for h in hr_data],
        },
    }


@get("/api/charts/hrv", sync_to_thread=False)
async def chart_hrv_data(
    request: Request[Any, Any, Any],
    session: AsyncSession,
    days: int = 30,
) -> dict[str, Any]:
    """Get HRV data from Nightly Recharge for charts.

    Returns HRV average and ANS charge for the last N days.
    """
    if not is_authenticated(request):
        return {"error": "Authentication required", "status": 401}

    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(NightlyRecharge)
        .where(NightlyRecharge.date >= since_date)
        .order_by(NightlyRecharge.date.asc())
    )
    result = await session.execute(stmt)
    recharge_data = result.scalars().all()

    return {
        "labels": [r.date.isoformat() for r in recharge_data],
        "datasets": {
            "hrv_avg": [r.hrv_avg or 0 for r in recharge_data],
            "ans_charge": [r.ans_charge or 0 for r in recharge_data],
        },
    }


@get("/api/charts/cardio-load", sync_to_thread=False)
async def chart_cardio_load_data(
    request: Request[Any, Any, Any],
    session: AsyncSession,
    days: int = 30,
) -> dict[str, Any]:
    """Get cardio load data for charts.

    Returns strain, tolerance, and load ratio for the last N days.
    """
    if not is_authenticated(request):
        return {"error": "Authentication required", "status": 401}

    since_date = date.today() - timedelta(days=days)
    stmt = select(CardioLoad).where(CardioLoad.date >= since_date).order_by(CardioLoad.date.asc())
    result = await session.execute(stmt)
    cardio_data = result.scalars().all()

    return {
        "labels": [c.date.isoformat() for c in cardio_data],
        "datasets": {
            "strain": [c.strain or 0 for c in cardio_data],
            "tolerance": [c.tolerance or 0 for c in cardio_data],
            "cardio_load": [c.cardio_load or 0 for c in cardio_data],
            "load_ratio": [
                round(c.cardio_load_ratio, 2) if c.cardio_load_ratio else 0 for c in cardio_data
            ],
        },
    }


# ============================================================================
# CSV Export Endpoints
# ============================================================================


@get("/export/sleep.csv", sync_to_thread=False)
async def export_sleep_csv(
    request: Request[Any, Any, Any],
    session: AsyncSession,
    days: int = 30,
) -> Response[bytes] | Redirect:
    """Export sleep data as CSV."""
    if not is_authenticated(request):
        return Redirect(path="/admin/login", status_code=HTTP_303_SEE_OTHER)

    since_date = date.today() - timedelta(days=days)
    stmt = select(Sleep).where(Sleep.date >= since_date).order_by(Sleep.date.asc())
    result = await session.execute(stmt)
    sleep_data = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["date", "sleep_score", "total_hours", "deep_hours", "light_hours", "rem_hours"]
    )

    for s in sleep_data:
        writer.writerow(
            [
                s.date.isoformat(),
                s.sleep_score,
                round(s.total_sleep_seconds / 3600, 2) if s.total_sleep_seconds else "",
                round(s.deep_sleep_seconds / 3600, 2) if s.deep_sleep_seconds else "",
                round(s.light_sleep_seconds / 3600, 2) if s.light_sleep_seconds else "",
                round(s.rem_sleep_seconds / 3600, 2) if s.rem_sleep_seconds else "",
            ]
        )

    return Response(
        content=output.getvalue().encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=sleep_{days}days.csv"},
    )


@get("/export/activity.csv", sync_to_thread=False)
async def export_activity_csv(
    request: Request[Any, Any, Any],
    session: AsyncSession,
    days: int = 30,
) -> Response[bytes] | Redirect:
    """Export activity data as CSV."""
    if not is_authenticated(request):
        return Redirect(path="/admin/login", status_code=HTTP_303_SEE_OTHER)

    since_date = date.today() - timedelta(days=days)
    stmt = select(Activity).where(Activity.date >= since_date).order_by(Activity.date.asc())
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


@get("/export/recharge.csv", sync_to_thread=False)
async def export_recharge_csv(
    request: Request[Any, Any, Any],
    session: AsyncSession,
    days: int = 30,
) -> Response[bytes] | Redirect:
    """Export recharge/HRV data as CSV."""
    if not is_authenticated(request):
        return Redirect(path="/admin/login", status_code=HTTP_303_SEE_OTHER)

    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(NightlyRecharge)
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


@get("/export/cardio-load.csv", sync_to_thread=False)
async def export_cardio_load_csv(
    request: Request[Any, Any, Any],
    session: AsyncSession,
    days: int = 30,
) -> Response[bytes] | Redirect:
    """Export cardio load data as CSV."""
    if not is_authenticated(request):
        return Redirect(path="/admin/login", status_code=HTTP_303_SEE_OTHER)

    since_date = date.today() - timedelta(days=days)
    stmt = select(CardioLoad).where(CardioLoad.date >= since_date).order_by(CardioLoad.date.asc())
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


# Export routes list
admin_routes = [
    # Public routes (no auth required)
    admin_index,
    setup_account_form,
    setup_account_submit,
    login_form,
    login_submit,
    logout,
    oauth_callback,  # OAuth callback must be accessible
    # Protected routes (auth required via session check in each route)
    save_oauth_credentials,
    admin_dashboard,
    trigger_manual_sync,
    oauth_authorize,
    admin_settings,
    reset_oauth_credentials,
    # Chart API endpoints
    chart_sleep_data,
    chart_activity_data,
    chart_heart_rate_data,
    chart_hrv_data,
    chart_cardio_load_data,
    # CSV Export endpoints
    export_sleep_csv,
    export_activity_csv,
    export_recharge_csv,
    export_cardio_load_csv,
]
