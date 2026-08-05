"""Admin panel routes."""

import asyncio
import csv
import io
import json
import logging
import os
import re
import secrets
from collections import OrderedDict
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from typing import Annotated, Any
from urllib.parse import quote, urlencode

import httpx
from litestar import Request, get, post
from litestar.exceptions import NotAuthorizedException
from litestar.params import Parameter
from litestar.response import Redirect, Response, Template
from litestar.status_codes import HTTP_200_OK, HTTP_303_SEE_OTHER
from polar_flow import PolarFlow
from polar_flow.exceptions import PolarFlowError
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
from polar_flow_server.core.api_keys import (
    create_api_key_for_user,
    regenerate_api_key,
    revoke_api_key,
)
from polar_flow_server.core.config import settings
from polar_flow_server.core.database import async_session_maker
from polar_flow_server.core.security import token_encryption
from polar_flow_server.core.setup_token import announce_setup_token, verify_setup_token
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
from polar_flow_server.models.sync_log import SyncLog, SyncTrigger
from polar_flow_server.models.temperature import BodyTemperature, SkinTemperature
from polar_flow_server.models.user import User
from polar_flow_server.services.scheduler import get_scheduler
from polar_flow_server.services.sync_guard import SyncInProgressError
from polar_flow_server.services.sync_orchestrator import SyncOrchestrator

logger = logging.getLogger(__name__)


# =============================================================================
# Bounded TTL Cache for OAuth States (prevents memory exhaustion)
# =============================================================================


class BoundedTTLCache:
    """Simple bounded cache with TTL for OAuth states.

    Prevents memory exhaustion attacks by limiting max entries.
    Automatically evicts expired entries on access.
    Thread-safe via asyncio lock.
    """

    def __init__(self, maxsize: int = 100, ttl_minutes: int = 10) -> None:
        self._cache: OrderedDict[str, datetime] = OrderedDict()
        self._maxsize = maxsize
        self._ttl = timedelta(minutes=ttl_minutes)
        self._lock = asyncio.Lock()

    async def set(self, key: str, expires_at: datetime | None = None) -> None:
        """Add or update a key with expiry time."""
        async with self._lock:
            self._cleanup_expired()
            # If at max, evict oldest entry and log warning
            if len(self._cache) >= self._maxsize:
                logger.warning(f"OAuth state cache full ({self._maxsize}), evicting oldest entries")
            while len(self._cache) >= self._maxsize:
                self._cache.popitem(last=False)
            self._cache[key] = expires_at or (datetime.now(UTC) + self._ttl)

    async def get(self, key: str) -> datetime | None:
        """Get expiry time for a key, or None if not found/expired."""
        async with self._lock:
            self._cleanup_expired()
            return self._cache.get(key)

    async def pop(self, key: str) -> datetime | None:
        """Remove and return expiry time for a key."""
        async with self._lock:
            return self._cache.pop(key, None)

    async def contains(self, key: str) -> bool:
        """Check if key exists (async version of __contains__)."""
        async with self._lock:
            self._cleanup_expired()
            return key in self._cache

    def _cleanup_expired(self) -> None:
        """Remove expired entries. Must be called with lock held."""
        now = datetime.now(UTC)
        # Use dict comprehension for atomic update
        self._cache = OrderedDict((k, exp) for k, exp in self._cache.items() if exp >= now)


# OAuth state storage with bounded size (prevents memory exhaustion)
_oauth_states = BoundedTTLCache(maxsize=100, ttl_minutes=10)


# =============================================================================
# Login Rate Limiting (prevents brute force attacks)
# =============================================================================


class LoginRateLimiter:
    """Simple in-memory rate limiter for login attempts.

    Tracks failed attempts by IP address and locks out after threshold.
    Thread-safe via asyncio lock.
    """

    def __init__(
        self, max_attempts: int = 5, lockout_minutes: int = 15, cleanup_interval: int = 100
    ) -> None:
        self._attempts: dict[str, list[datetime]] = {}
        self._lockouts: dict[str, datetime] = {}
        self._max_attempts = max_attempts
        self._lockout_duration = timedelta(minutes=lockout_minutes)
        self._attempt_window = timedelta(minutes=15)
        self._cleanup_counter = 0
        self._cleanup_interval = cleanup_interval
        self._lock = asyncio.Lock()

    async def is_locked_out(self, ip: str) -> bool:
        """Check if IP is currently locked out."""
        async with self._lock:
            self._maybe_cleanup()
            lockout_until = self._lockouts.get(ip)
            if lockout_until and lockout_until > datetime.now(UTC):
                return True
            # Clear expired lockout
            if lockout_until:
                del self._lockouts[ip]
            return False

    async def record_failure(self, ip: str) -> bool:
        """Record a failed login attempt. Returns True if now locked out."""
        async with self._lock:
            now = datetime.now(UTC)
            self._maybe_cleanup()

            # Get recent attempts within window
            attempts = self._attempts.get(ip, [])
            cutoff = now - self._attempt_window
            attempts = [t for t in attempts if t > cutoff]
            attempts.append(now)
            self._attempts[ip] = attempts

            # Check if should lock out
            if len(attempts) >= self._max_attempts:
                self._lockouts[ip] = now + self._lockout_duration
                logger.warning(f"Login rate limit exceeded for IP {ip}, locked out")
                return True
            return False

    async def record_success(self, ip: str) -> None:
        """Clear attempts on successful login."""
        async with self._lock:
            self._attempts.pop(ip, None)
            self._lockouts.pop(ip, None)

    def _maybe_cleanup(self) -> None:
        """Periodically clean up old entries. Must be called with lock held."""
        self._cleanup_counter += 1
        if self._cleanup_counter < self._cleanup_interval:
            return
        self._cleanup_counter = 0

        now = datetime.now(UTC)
        cutoff = now - self._attempt_window

        # Atomic cleanup using dict comprehension
        self._attempts = {
            ip: [t for t in attempts if t > cutoff]
            for ip, attempts in self._attempts.items()
            if any(t > cutoff for t in attempts)
        }
        self._lockouts = {ip: exp for ip, exp in self._lockouts.items() if exp >= now}


# Global rate limiter instance
_login_rate_limiter = LoginRateLimiter(max_attempts=5, lockout_minutes=15)

# Serializes first-run admin creation (see setup_account_submit)
_setup_lock = asyncio.Lock()

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


async def _connected_user_id(session: AsyncSession) -> str | None:
    """polar_user_id of the connected user, or None before OAuth setup.

    Health-data queries must be scoped to this user (same rule the CSV
    exports follow) so a second user row never leaks into the dashboard.
    """
    result = await session.execute(select(User).where(User.is_active == True).limit(1))  # noqa: E712
    user = result.scalar_one_or_none()
    return user.polar_user_id if user else None


_ZONE_COLORS = ["bg-sky-300", "bg-teal-400", "bg-lime-400", "bg-amber-400", "bg-red-400"]


def _format_workouts(exercises: Sequence[Exercise]) -> list[dict[str, Any]]:
    """Prepare Exercise rows for the dashboard's Recent Workouts card.

    Formats duration/distance for display and parses the stored HR-zone
    JSON (present only on exercises synced with detail flags) into
    percentage-width segments for the zone bar.
    """
    workouts: list[dict[str, Any]] = []
    for ex in exercises:
        duration = None
        if ex.duration_seconds:
            hours, rem = divmod(ex.duration_seconds, 3600)
            minutes = rem // 60
            duration = f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"

        # Stored JSON with no schema enforcement must never take down the
        # whole dashboard - bad zone data just means no bar for that workout
        zones = None
        if ex.heart_rate_zones_json:
            try:
                raw = sorted(json.loads(ex.heart_rate_zones_json), key=lambda z: z["index"])
                total = sum(z.get("in_zone_seconds") or 0 for z in raw)
                if total > 0:
                    zones = [
                        {
                            "index": z["index"],
                            "percent": round((z.get("in_zone_seconds") or 0) * 100 / total, 1),
                            "minutes": round((z.get("in_zone_seconds") or 0) / 60),
                            "color": _ZONE_COLORS[min(max(z["index"], 1), 5) - 1],
                            "limits": f"{z.get('lower_limit_bpm', '?')}-{z.get('upper_limit_bpm', '?')} bpm",
                        }
                        for z in raw
                    ]
            except (ValueError, TypeError, KeyError):
                logger.warning("Skipping malformed heart_rate_zones_json for exercise %s", ex.id)

        workouts.append(
            {
                "date": ex.start_time.strftime("%a %d %b"),
                "time": ex.start_time.strftime("%H:%M"),
                "sport": (ex.detailed_sport_info or ex.sport or "Workout")
                .replace("_", " ")
                .title(),
                "duration": duration,
                "distance_km": (
                    round(ex.distance_meters / 1000, 2) if ex.distance_meters else None
                ),
                "avg_hr": ex.average_heart_rate,
                "max_hr": ex.max_heart_rate,
                "calories": ex.calories,
                "training_load": round(ex.training_load, 1) if ex.training_load else None,
                "running_index": ex.running_index,
                "has_route": bool(ex.route_json),
                "zones": zones,
            }
        )
    return workouts


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

    Metrics older than 48h are excluded rather than silently blended in —
    "Today's Readiness" built on last week's sleep is worse than no number.
    """
    stale_cutoff = date.today() - timedelta(days=2)
    if sleep and sleep.date < stale_cutoff:
        sleep = None
    if recharge and recharge.date < stale_cutoff:
        recharge = None
    if cardio and cardio.date < stale_cutoff:
        cardio = None

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

    # HRV/ANS factor (0-100), normalized from Polar's ANS charge scale (-10 to +10)
    ans_score: float = 50.0  # default
    if recharge:
        if recharge.ans_charge is not None:
            ans_score = min(100.0, max(0.0, (float(recharge.ans_charge) + 10.0) * 5.0))
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

    # (Re-)print the token so `docker logs` right after loading this page
    # always shows it — visitors only see the form, never the token.
    announce_setup_token()

    return Template(
        template_name="admin/setup_account.html",
        context={"csrf_token": _get_csrf_token(request)},
    )


@post("/setup/account", sync_to_thread=False)
async def setup_account_submit(
    request: Request[Any, Any, Any], session: AsyncSession
) -> Template | Redirect:
    """Create the first admin account.

    Only accessible if no admin user exists yet, and only with the setup
    token from the server log — otherwise the first visitor to reach an
    exposed instance could claim it.
    """
    if await admin_user_exists(session):
        return Redirect(path="/admin", status_code=HTTP_303_SEE_OTHER)

    form_data = await request.form()
    email = form_data.get("email", "").strip()
    password = form_data.get("password", "")
    password_confirm = form_data.get("password_confirm", "")
    name = form_data.get("name", "").strip() or None
    setup_token = str(form_data.get("setup_token", ""))

    # Validation
    errors = []
    if not verify_setup_token(setup_token):
        errors.append("Invalid setup token — check the server logs for the current one")

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

    # Create admin user. Serialize check+create so two concurrent submits
    # can't both pass the exists-check and create two admins.
    try:
        async with _setup_lock:
            if await admin_user_exists(session):
                return Redirect(path="/admin", status_code=HTTP_303_SEE_OTHER)
            admin = await create_admin_user(
                email=str(email),
                password=str(password),
                session=session,
                name=str(name) if name else None,
            )
        # Log them in immediately
        await login_admin(request, admin)
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
        context={
            "csrf_token": _get_csrf_token(request),
            "next": _safe_next_path(request.query_params.get("next")),
        },
    )


def _safe_next_path(raw: str | None) -> str | None:
    """Only allow post-login redirects to admin-local paths (no open redirect)."""
    if raw and raw.startswith("/admin/") and "//" not in raw and "\\" not in raw:
        return raw
    return None


def _trusted_proxy_matchers() -> tuple[set[str], list[IPv4Network | IPv6Network]]:
    """Parse settings.trusted_proxies into literal hosts and IP networks."""
    literals: set[str] = set()
    networks: list[IPv4Network | IPv6Network] = []
    for entry in settings.trusted_proxies.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ip_network(entry, strict=False))
        except ValueError:
            # Not an IP/CIDR — treat as a literal peer name (e.g. "localhost")
            literals.add(entry)
    return literals, networks


def _is_trusted_proxy(host: str) -> bool:
    literals, networks = _trusted_proxy_matchers()
    if host in literals:
        return True
    try:
        addr = ip_address(host)
    except ValueError:
        return False
    return any(addr in network for network in networks)


def _get_client_ip(request: Request[Any, Any, Any]) -> str:
    """Get the real client IP, honouring proxy headers only from trusted proxies.

    The direct peer must be in TRUSTED_PROXIES (IPs/CIDRs, e.g. the Docker
    network the reverse proxy lives on) for X-Forwarded-For/X-Real-IP to be
    considered at all. X-Forwarded-For is then walked right-to-left, skipping
    trusted proxies: the first untrusted hop is the client. Never take the
    leftmost entry — clients can prepend arbitrary values before the proxy
    appends the real address, which would let an attacker pick their own
    identity (dodging rate limits or locking out a victim's IP).
    """
    client = request.client
    direct_ip = client.host if client else "unknown"

    if not _is_trusted_proxy(direct_ip):
        return direct_ip

    forwarded_for = request.headers.get("x-forwarded-for", "")
    hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
    for hop in reversed(hops):
        if not _is_trusted_proxy(hop):
            return hop
    if hops:
        # Every hop is a trusted proxy — the innermost is the closest to a client
        return hops[0]

    # X-Real-IP is set (not appended) by the proxy itself, safe from trusted peers
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    return direct_ip


@post("/login", sync_to_thread=False)
async def login_submit(
    request: Request[Any, Any, Any], session: AsyncSession
) -> Template | Redirect:
    """Process login form submission."""
    client_ip = _get_client_ip(request)

    # Check if IP is locked out due to too many failed attempts
    if await _login_rate_limiter.is_locked_out(client_ip):
        return Template(
            template_name="admin/login.html",
            context={
                "error": "Too many failed attempts. Please try again later.",
                "email": "",
                "csrf_token": _get_csrf_token(request),
            },
        )

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
        # Record failed attempt
        await _login_rate_limiter.record_failure(client_ip)
        return Template(
            template_name="admin/login.html",
            context={
                "error": "Invalid credentials",
                "email": email,
                "csrf_token": _get_csrf_token(request),
            },
        )

    # Successful login - clear any failed attempts
    await _login_rate_limiter.record_success(client_ip)
    await login_admin(request, admin)
    next_path = _safe_next_path(str(form_data.get("next", "")) or None)
    return Redirect(path=next_path or "/admin", status_code=HTTP_303_SEE_OTHER)


@post("/logout", sync_to_thread=False)
async def logout(request: Request[Any, Any, Any]) -> Redirect:
    """Log out and redirect to login page."""
    logout_admin(request)
    return Redirect(path="/admin/login", status_code=HTTP_303_SEE_OTHER)


# =============================================================================
# OAuth consent (the human half of the MCP connector sign-in flow)
#
# The SDK's /authorize endpoint validates the client and redirects here with
# a signed blob of the authorization params. The admin logs in (if needed),
# approves or denies, and we redirect back to the client with a code or an
# access_denied error. Only exists when BASE_URL is configured (self-hosted).
# =============================================================================


def _consent_error(request: Request[Any, Any, Any], message: str) -> Template:
    return Template(
        template_name="admin/oauth_consent.html",
        context={"error": message, "csrf_token": _get_csrf_token(request)},
    )


@get("/oauth/consent", sync_to_thread=False)
async def oauth_consent_form(
    request: Request[Any, Any, Any], session: AsyncSession
) -> Template | Redirect:
    """Show the consent screen for a pending OAuth authorization request."""
    if not is_authenticated(request):
        target = quote(f"/admin/oauth/consent?req={request.query_params.get('req', '')}", safe="")
        return Redirect(path=f"/admin/login?next={target}", status_code=HTTP_303_SEE_OTHER)

    from polar_flow_server.mcp_server.oauth import PolarOAuthProvider, unpack_consent_request

    data = unpack_consent_request(str(request.query_params.get("req", "")))
    if data is None:
        return _consent_error(
            request, "This authorization request is invalid or has expired. Retry from the app."
        )

    client = await PolarOAuthProvider().get_client(data["client_id"])
    if client is None:
        return _consent_error(request, "Unknown application. Retry the connection from the app.")

    user_id = await _connected_user_id(session)
    if user_id is None:
        return _consent_error(
            request, "No Polar account is connected yet - complete setup before authorizing apps."
        )

    return Template(
        template_name="admin/oauth_consent.html",
        context={
            "client_name": client.client_name or client.client_id,
            "user_id": user_id,
            "req": request.query_params.get("req", ""),
            "csrf_token": _get_csrf_token(request),
        },
    )


@post("/oauth/consent", sync_to_thread=False)
async def oauth_consent_submit(
    request: Request[Any, Any, Any], session: AsyncSession
) -> Template | Redirect:
    """Complete a consent decision: mint a code (approve) or bounce (deny)."""
    if not is_authenticated(request):
        return Redirect(path="/admin/login", status_code=HTTP_303_SEE_OTHER)

    from mcp.server.auth.provider import construct_redirect_uri

    from polar_flow_server.mcp_server.oauth import (
        PolarOAuthProvider,
        build_consent_redirect,
        unpack_consent_request,
    )

    form_data = await request.form()
    data = unpack_consent_request(str(form_data.get("req", "")))
    if data is None:
        return _consent_error(
            request, "This authorization request is invalid or has expired. Retry from the app."
        )

    # The hop back to the client CANNOT be a redirect response to this form
    # POST: browsers enforce the page's form-action CSP ('self') against the
    # whole redirect chain, so a 303 to the client's origin gets blocked.
    # Render a self-navigating page instead - plain navigation is not
    # subject to form-action, and it works for any client origin without
    # loosening the CSP.
    if form_data.get("action") != "approve":
        return Template(
            template_name="admin/oauth_redirect.html",
            context={
                "target": construct_redirect_uri(
                    data["redirect_uri"], error="access_denied", state=data["state"]
                ),
                "denied": True,
            },
        )

    user_id = await _connected_user_id(session)
    if user_id is None:
        return _consent_error(
            request, "No Polar account is connected yet - complete setup before authorizing apps."
        )

    code = await PolarOAuthProvider().create_authorization_code(data, user_id)
    return Template(
        template_name="admin/oauth_redirect.html",
        context={"target": build_consent_redirect(data, code), "denied": False},
    )


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

    # All health-data queries below are scoped to the connected user, matching
    # the CSV exports — with >1 user row an unscoped "latest" mixes users' data.
    uid = await _connected_user_id(session)

    def scoped(stmt: Any, model: Any) -> Any:
        return stmt.where(model.user_id == uid) if uid else stmt

    since_date = date.today() - timedelta(days=7)

    # ~17 independent lookups used to run as sequential round trips — on a
    # remote Postgres that's ~17x RTT per page view (issue #87). They are
    # built up front and executed concurrently, each on a short-lived
    # session, so wall-clock is roughly one round trip. Statements are
    # unchanged; only the scheduling differs.
    stmts: dict[str, Any] = {
        "recent_sleep": scoped(
            select(Sleep).where(Sleep.date >= since_date).order_by(Sleep.date.desc()).limit(7),
            Sleep,
        ),
        "latest_hrv": scoped(
            select(NightlyRecharge)
            .where(NightlyRecharge.hrv_avg.isnot(None))
            .order_by(NightlyRecharge.date.desc())
            .limit(1),
            NightlyRecharge,
        ),
        "resting_hr": scoped(
            select(NightlyRecharge)
            .where(NightlyRecharge.heart_rate_avg.isnot(None))
            .order_by(NightlyRecharge.date.desc())
            .limit(1),
            NightlyRecharge,
        ),
        "latest_cardio": scoped(
            select(CardioLoad).order_by(CardioLoad.date.desc()).limit(1), CardioLoad
        ),
        "latest_hr": scoped(
            select(ContinuousHeartRate).order_by(ContinuousHeartRate.date.desc()).limit(1),
            ContinuousHeartRate,
        ),
        "latest_alertness": scoped(
            select(SleepWiseAlertness)
            .order_by(SleepWiseAlertness.period_start_time.desc())
            .limit(1),
            SleepWiseAlertness,
        ),
        "latest_spo2": scoped(select(SpO2).order_by(SpO2.test_time.desc()).limit(1), SpO2),
        # Both biosensing counts in one SELECT via scalar subqueries
        "bio_counts": select(
            scoped(select(func.count(SpO2.id)), SpO2).scalar_subquery().label("spo2"),
            scoped(select(func.count(ECG.id)), ECG).scalar_subquery().label("ecg"),
        ),
        "latest_skin_temp": scoped(
            select(SkinTemperature).order_by(SkinTemperature.sleep_date.desc()).limit(1),
            SkinTemperature,
        ),
        "latest_activity": scoped(
            select(Activity).order_by(Activity.date.desc()).limit(1), Activity
        ),
        "latest_activity_samples": scoped(
            select(ActivitySamples).order_by(ActivitySamples.date.desc()).limit(1), ActivitySamples
        ),
        "breathing": scoped(
            select(NightlyRecharge)
            .where(NightlyRecharge.breathing_rate_avg.isnot(None))
            .order_by(NightlyRecharge.date.desc())
            .limit(1),
            NightlyRecharge,
        ),
        "recent_recharge": scoped(
            select(NightlyRecharge)
            .where(NightlyRecharge.date >= since_date)
            .order_by(NightlyRecharge.date.desc())
            .limit(7),
            NightlyRecharge,
        ),
        "recent_exercises": scoped(
            select(Exercise).order_by(Exercise.start_time.desc()).limit(20), Exercise
        ),
        "sync_logs": select(SyncLog).order_by(SyncLog.started_at.desc()).limit(10),
    }
    if uid:
        stmts["baselines"] = (
            select(UserBaseline)
            .where(UserBaseline.user_id == uid)
            .order_by(UserBaseline.metric_name)
        )
        stmts["patterns"] = (
            select(PatternAnalysis)
            .where(PatternAnalysis.user_id == uid)
            .order_by(PatternAnalysis.significance.desc(), PatternAnalysis.analyzed_at.desc())
        )

    async def _run(stmt: Any) -> Any:
        async with async_session_maker() as short_session:
            return await short_session.execute(stmt)

    gathered = await asyncio.gather(*(_run(stmt) for stmt in stmts.values()))
    results = dict(zip(stmts.keys(), gathered, strict=True))

    recent_sleep = results["recent_sleep"].scalars().all()
    latest_recharge = results["latest_hrv"].scalar_one_or_none()
    latest_hrv = latest_recharge.hrv_avg if latest_recharge else None
    resting_hr_record = results["resting_hr"].scalar_one_or_none()
    latest_resting_hr = resting_hr_record.heart_rate_avg if resting_hr_record else None
    latest_cardio = results["latest_cardio"].scalar_one_or_none()
    latest_hr = results["latest_hr"].scalar_one_or_none()
    latest_alertness = results["latest_alertness"].scalar_one_or_none()
    latest_spo2 = results["latest_spo2"].scalar_one_or_none()
    bio_counts = results["bio_counts"].one()
    spo2_count = bio_counts.spo2 or 0
    ecg_count = bio_counts.ecg or 0
    latest_skin_temp = results["latest_skin_temp"].scalar_one_or_none()
    latest_activity = results["latest_activity"].scalar_one_or_none()
    latest_activity_samples = results["latest_activity_samples"].scalar_one_or_none()
    breathing_record = results["breathing"].scalar_one_or_none()
    latest_breathing_rate = breathing_record.breathing_rate_avg if breathing_record else None
    recent_recharge = results["recent_recharge"].scalars().all()
    recent_workouts = _format_workouts(results["recent_exercises"].scalars().all())
    recent_sync_logs = results["sync_logs"].scalars().all()
    user_baselines: list[UserBaseline] = list(results["baselines"].scalars().all()) if uid else []
    user_patterns: list[PatternAnalysis] = list(results["patterns"].scalars().all()) if uid else []

    # Calculate recovery recommendations
    recovery_status = _calculate_recovery_status(
        sleep=recent_sleep[0] if recent_sleep else None,
        recharge=latest_recharge,
        cardio=latest_cardio,
    )

    # Record dates feeding the stat tiles' age badges (issue #70): the tiles
    # show "latest" values, which can silently be days old after a sync gap.
    tile_dates = {
        "hrv": latest_recharge.date if latest_recharge else None,
        "sleep": recent_sleep[0].date if recent_sleep else None,
        "breathing": breathing_record.date if breathing_record else None,
        "alertness": latest_alertness.period_start_time.date() if latest_alertness else None,
        "resting_hr": resting_hr_record.date if resting_hr_record else None,
        "daily_hr": latest_hr.date if latest_hr else None,
        "spo2": latest_spo2.test_time.date() if latest_spo2 else None,
        "skin_temp": latest_skin_temp.sleep_date if latest_skin_temp else None,
        "activity": latest_activity.date if latest_activity else None,
        "cardio": latest_cardio.date if latest_cardio else None,
    }

    return Template(
        template_name="admin/dashboard.html",
        context={
            # Latest data
            "recent_sleep": recent_sleep,
            "tile_dates": tile_dates,
            "recent_recharge": recent_recharge,
            "latest_hrv": latest_hrv,
            "latest_resting_hr": latest_resting_hr,
            "latest_cardio": latest_cardio,
            "latest_hr": latest_hr,
            "latest_alertness": latest_alertness,
            "latest_spo2": latest_spo2,
            "latest_skin_temp": latest_skin_temp,
            "spo2_count": spo2_count,
            "ecg_count": ecg_count,
            "latest_activity": latest_activity,
            "latest_activity_samples": latest_activity_samples,
            "latest_breathing_rate": latest_breathing_rate,
            # Recovery
            "recovery_status": recovery_status,
            # Workouts (training tab)
            "recent_workouts": recent_workouts,
            # Sync history (for top badge)
            "recent_sync_logs": recent_sync_logs,
            # Analytics
            "user_baselines": user_baselines,
            "user_patterns": user_patterns,
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

    # Run sync via orchestrator (creates SyncLog entry for audit trail)
    orchestrator = SyncOrchestrator(session)
    try:
        sync_log = await orchestrator.sync_user(
            user_id=user_id,
            polar_token=polar_token,
            trigger=SyncTrigger.MANUAL,
        )

        # Check sync status
        if sync_log.status == "partial":
            # Partial success - some endpoints worked, some failed
            errors = sync_log.error_details.get("errors", {}) if sync_log.error_details else {}
            return Template(
                template_name="admin/partials/sync_partial.html",
                context={
                    "results": sync_log.records_synced or {},
                    "errors": errors,
                },
            )
        elif sync_log.status == "failed":
            # Total failure - all endpoints failed
            errors_raw = sync_log.error_details.get("errors", {}) if sync_log.error_details else {}
            # errors_raw is dict[str, str] but typed as object, cast for iteration
            errors = errors_raw if isinstance(errors_raw, dict) else {}
            if errors:
                error_messages = "\n".join(
                    f"• {endpoint}: {msg}" for endpoint, msg in errors.items()
                )
            else:
                error_messages = sync_log.error_message or "Sync failed"
            return Template(
                template_name="admin/partials/sync_error.html",
                context={"error": error_messages},
            )

        # Full success - no errors
        return Template(
            template_name="admin/partials/sync_success.html",
            context={
                "results": sync_log.records_synced or {},
            },
        )
    except SyncInProgressError:
        return Template(
            template_name="admin/partials/sync_error.html",
            context={
                "error": (
                    "A sync is already running. Wait for it to finish — "
                    "it will appear in the sync history below."
                )
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

    # Generate CSRF state token (BoundedTTLCache handles cleanup and size limits)
    state = secrets.token_urlsafe(32)
    await _oauth_states.set(state)

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
    if not state or not await _oauth_states.contains(state):
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": "Invalid OAuth state - possible CSRF attack. Please try again."},
        )

    # Get and remove state (one-time use) - also checks expiry
    state_expires = await _oauth_states.pop(state)
    if state_expires and state_expires < datetime.now(UTC):
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": "OAuth state expired. Please try again."},
        )

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
        access_token = token_data["access_token"]

        # Register user with Polar AccessLink API (required before data access).
        # Without this step, all data endpoints return 403 Forbidden.
        # 409 = already registered, which is fine.
        async with PolarFlow(access_token=access_token) as polar_client:
            try:
                await polar_client.users.register(member_id=polar_user_id)
                logger.info(f"Registered Polar user {polar_user_id} with AccessLink API")
            except PolarFlowError as e:
                if e.status_code == 409:
                    logger.debug(f"Polar user {polar_user_id} already registered (409)")
                else:
                    raise

        access_token_encrypted = token_encryption.encrypt(access_token)

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

    # Get API keys
    api_keys_stmt = select(APIKey).order_by(APIKey.created_at.desc())
    api_keys_result = await session.execute(api_keys_stmt)
    api_keys = api_keys_result.scalars().all()

    # All 15 data counts in ONE round trip (issue #87): scalar subqueries in
    # a single SELECT instead of 15 sequential queries (~15x RTT on a remote
    # Postgres).
    count_models: dict[str, Any] = {
        "sleep_count": Sleep,
        "exercise_count": Exercise,
        "activity_count": Activity,
        "recharge_count": NightlyRecharge,
        "cardio_load_count": CardioLoad,
        "alertness_count": SleepWiseAlertness,
        "bedtime_count": SleepWiseBedtime,
        "activity_samples_count": ActivitySamples,
        "continuous_hr_count": ContinuousHeartRate,
        "spo2_count": SpO2,
        "ecg_count": ECG,
        "body_temp_count": BodyTemperature,
        "skin_temp_count": SkinTemperature,
        "baseline_count": UserBaseline,
        "pattern_count": PatternAnalysis,
    }
    counts_stmt = select(
        *(
            select(func.count(model.id)).scalar_subquery().label(name)
            for name, model in count_models.items()
        )
    )
    counts = (await session.execute(counts_stmt)).one()._asdict()
    sleep_count = counts["sleep_count"] or 0
    exercise_count = counts["exercise_count"] or 0
    activity_count = counts["activity_count"] or 0
    recharge_count = counts["recharge_count"] or 0
    cardio_load_count = counts["cardio_load_count"] or 0
    alertness_count = counts["alertness_count"] or 0
    bedtime_count = counts["bedtime_count"] or 0
    activity_samples_count = counts["activity_samples_count"] or 0
    continuous_hr_count = counts["continuous_hr_count"] or 0
    spo2_count = counts["spo2_count"] or 0
    ecg_count = counts["ecg_count"] or 0
    body_temp_count = counts["body_temp_count"] or 0
    skin_temp_count = counts["skin_temp_count"] or 0
    baseline_count = counts["baseline_count"] or 0
    pattern_count = counts["pattern_count"] or 0

    # Get scheduler status
    scheduler = get_scheduler()
    scheduler_status = (
        scheduler.get_status()
        if scheduler
        else {
            "enabled": settings.sync_enabled,
            "is_running": False,
            "interval_minutes": settings.sync_interval_minutes,
            "next_run_at": None,
            "last_run_at": None,
            "last_run_stats": None,
        }
    )

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

    # MCP connector apps (OAuth clients) with their live token counts
    from polar_flow_server.models.oauth import OAuthClient, OAuthIssuedToken

    oauth_clients = (
        (await session.execute(select(OAuthClient).order_by(OAuthClient.created_at.desc())))
        .scalars()
        .all()
    )
    now_ts = datetime.now(UTC).timestamp()
    token_count_rows = (
        await session.execute(
            select(OAuthIssuedToken.client_id, func.count())
            .where(
                OAuthIssuedToken.revoked == False,  # noqa: E712
                OAuthIssuedToken.token_type == "access",
                OAuthIssuedToken.expires_at > now_ts,
            )
            .group_by(OAuthIssuedToken.client_id)
        )
    ).all()
    token_counts: dict[str, int] = {str(cid): int(n) for cid, n in token_count_rows}
    oauth_apps = [
        {
            "client_id": c.client_id,
            "name": c.client_metadata.get("client_name") or c.client_id,
            "created_at": c.created_at,
            "active_tokens": token_counts.get(c.client_id, 0),
        }
        for c in oauth_clients
    ]

    return Template(
        template_name="admin/settings.html",
        context={
            "csrf_token": _get_csrf_token(request),
            "oauth_apps": oauth_apps,
            "has_credentials": bool(app_settings and app_settings.polar_client_id),
            "client_id": app_settings.polar_client_id if app_settings else None,
            "connected_user": connected_user,
            "api_keys": api_keys,
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
            # Sync scheduler
            "sync_interval_minutes": settings.sync_interval_minutes,
            "sync_days_lookback": settings.sync_days_lookback,
            "scheduler_status": scheduler_status,
            "recent_sync_logs": recent_sync_logs,
            "sync_stats": sync_stats,
        },
    )


@post("/oauth-apps/revoke", sync_to_thread=False)
async def revoke_oauth_app(request: Request[Any, Any, Any], session: AsyncSession) -> Redirect:
    """Revoke every token an MCP connector app holds (from Settings)."""
    if not is_authenticated(request):
        return Redirect(path="/admin/login", status_code=HTTP_303_SEE_OTHER)

    from sqlalchemy import update as sa_update

    from polar_flow_server.models.oauth import OAuthIssuedToken

    form_data = await request.form()
    client_id = str(form_data.get("client_id", ""))
    if client_id:
        await session.execute(
            sa_update(OAuthIssuedToken)
            .where(OAuthIssuedToken.client_id == client_id)
            .values(revoked=True)
        )
        await session.commit()
    return Redirect(path="/admin/settings", status_code=HTTP_303_SEE_OTHER)


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
# API Key Management (Admin-authenticated, no API key required)
# ============================================================================
#
# Authorization Model:
# These routes use session-based admin authentication, not per-key authorization.
# The admin who logs into the dashboard has full access to manage all API keys.
# This is intentional:
# - Self-hosted: Single admin manages all keys for their deployment
# - SaaS: System admin manages keys across all users
#
# Per-key ownership checks are not needed since admin access itself is the
# authorization boundary. If you need user-level key management, use the
# per-user API endpoints in api/keys.py which require API key authentication.


@post("/api-keys/{key_id:int}/regenerate", sync_to_thread=False, status_code=HTTP_200_OK)
async def admin_regenerate_api_key(
    request: Request[Any, Any, Any],
    session: AsyncSession,
    key_id: int,
) -> Template:
    """Regenerate an API key from the admin panel.

    Uses session authentication (admin login), not API key auth.
    This allows admins to regenerate keys when the original is lost.
    """
    if not is_authenticated(request):
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": "Authentication required. Please log in."},
        )

    try:
        # Find the API key by ID
        stmt = select(APIKey).where(APIKey.id == key_id)
        result = await session.execute(stmt)
        api_key = result.scalar_one_or_none()

        if not api_key:
            return Template(
                template_name="admin/partials/sync_error.html",
                context={"error": f"API key with ID {key_id} not found."},
            )

        if not api_key.is_active:
            return Template(
                template_name="admin/partials/sync_error.html",
                context={"error": "Cannot regenerate a revoked key. The key must be active."},
            )

        # Regenerate the key
        new_raw_key = await regenerate_api_key(api_key, session)
        await session.commit()

        return Template(
            template_name="admin/partials/api_key_regenerated.html",
            context={
                "api_key": new_raw_key,
                "key_prefix": api_key.key_prefix,
                "key_name": api_key.name,
            },
        )

    except Exception as e:
        await session.rollback()
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": f"Failed to regenerate key: {str(e)}"},
        )


@post("/api-keys/{key_id:int}/revoke", sync_to_thread=False, status_code=HTTP_200_OK)
async def admin_revoke_api_key(
    request: Request[Any, Any, Any],
    session: AsyncSession,
    key_id: int,
) -> Template:
    """Revoke an API key from the admin panel.

    Uses session authentication (admin login), not API key auth.
    """
    if not is_authenticated(request):
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": "Authentication required. Please log in."},
        )

    try:
        # Find the API key by ID
        stmt = select(APIKey).where(APIKey.id == key_id)
        result = await session.execute(stmt)
        api_key = result.scalar_one_or_none()

        if not api_key:
            return Template(
                template_name="admin/partials/sync_error.html",
                context={"error": f"API key with ID {key_id} not found."},
            )

        if not api_key.is_active:
            return Template(
                template_name="admin/partials/sync_error.html",
                context={"error": "Key is already revoked."},
            )

        # Revoke the key
        await revoke_api_key(api_key, session)
        await session.commit()

        return Template(
            template_name="admin/partials/api_key_revoked.html",
            context={
                "key_prefix": api_key.key_prefix,
                "key_name": api_key.name,
            },
        )

    except Exception as e:
        await session.rollback()
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": f"Failed to revoke key: {str(e)}"},
        )


@post("/api-keys/create", sync_to_thread=False, status_code=HTTP_200_OK)
async def admin_create_api_key(
    request: Request[Any, Any, Any],
    session: AsyncSession,
) -> Template:
    """Create a new API key for the connected user from the admin panel.

    Uses session authentication (admin login), not API key auth.
    """
    if not is_authenticated(request):
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": "Authentication required. Please log in."},
        )

    try:
        # Get the connected user
        stmt = select(User).where(User.is_active == True).limit(1)  # noqa: E712
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            return Template(
                template_name="admin/partials/sync_error.html",
                context={"error": "No connected user found. Please connect via OAuth first."},
            )

        # Check if user already has an active key
        key_stmt = select(APIKey).where(
            APIKey.user_id == user.polar_user_id,
            APIKey.is_active == True,  # noqa: E712
        )
        key_result = await session.execute(key_stmt)
        existing_key = key_result.scalar_one_or_none()

        if existing_key:
            return Template(
                template_name="admin/partials/sync_error.html",
                context={"error": "User already has an active API key. Use regenerate instead."},
            )

        # Create the API key
        api_key, raw_key = await create_api_key_for_user(
            user_id=user.polar_user_id,
            name=f"Admin-created key for {user.polar_user_id}",
            session=session,
        )
        await session.commit()

        return Template(
            template_name="admin/partials/api_key_regenerated.html",
            context={
                "api_key": raw_key,
                "key_prefix": api_key.key_prefix,
                "key_name": api_key.name,
            },
        )

    except Exception as e:
        await session.rollback()
        return Template(
            template_name="admin/partials/sync_error.html",
            context={"error": f"Failed to create key: {str(e)}"},
        )


# ============================================================================
# Chart Data API Routes (JSON endpoints for Chart.js)
# ============================================================================


@get("/api/charts/sleep", sync_to_thread=False)
async def chart_sleep_data(
    request: Request[Any, Any, Any],
    session: AsyncSession,
    days: Annotated[int, Parameter(ge=1, le=365)] = 30,
) -> dict[str, Any]:
    """Get sleep data for charts.

    Returns sleep score, duration, and stage breakdown for the last N days.
    """
    if not is_authenticated(request):
        raise NotAuthorizedException(detail="Authentication required")

    uid = await _connected_user_id(session)
    since_date = date.today() - timedelta(days=days)
    stmt = select(Sleep).where(Sleep.date >= since_date).order_by(Sleep.date.asc())
    if uid:
        stmt = stmt.where(Sleep.user_id == uid)
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
    days: Annotated[int, Parameter(ge=1, le=365)] = 30,
) -> dict[str, Any]:
    """Get activity data for charts.

    Returns steps, calories, and active time for the last N days.
    """
    if not is_authenticated(request):
        raise NotAuthorizedException(detail="Authentication required")

    uid = await _connected_user_id(session)
    since_date = date.today() - timedelta(days=days)
    stmt = select(Activity).where(Activity.date >= since_date).order_by(Activity.date.asc())
    if uid:
        stmt = stmt.where(Activity.user_id == uid)
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
    days: Annotated[int, Parameter(ge=1, le=365)] = 30,
) -> dict[str, Any]:
    """Get heart rate data for charts.

    Returns min/avg/max heart rate for the last N days.
    """
    if not is_authenticated(request):
        raise NotAuthorizedException(detail="Authentication required")

    uid = await _connected_user_id(session)
    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(ContinuousHeartRate)
        .where(ContinuousHeartRate.date >= since_date)
        .order_by(ContinuousHeartRate.date.asc())
    )
    if uid:
        stmt = stmt.where(ContinuousHeartRate.user_id == uid)
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
    days: Annotated[int, Parameter(ge=1, le=365)] = 30,
) -> dict[str, Any]:
    """Get HRV data from Nightly Recharge for charts.

    Returns HRV average and ANS charge for the last N days.
    """
    if not is_authenticated(request):
        raise NotAuthorizedException(detail="Authentication required")

    uid = await _connected_user_id(session)
    since_date = date.today() - timedelta(days=days)
    stmt = (
        select(NightlyRecharge)
        .where(NightlyRecharge.date >= since_date)
        .order_by(NightlyRecharge.date.asc())
    )
    if uid:
        stmt = stmt.where(NightlyRecharge.user_id == uid)
    result = await session.execute(stmt)
    recharge_data = result.scalars().all()

    return {
        "labels": [r.date.isoformat() for r in recharge_data],
        "datasets": {
            "hrv_avg": [r.hrv_avg or 0 for r in recharge_data],
            "ans_charge": [
                r.ans_charge if r.ans_charge is not None else None for r in recharge_data
            ],
        },
    }


@get("/api/charts/cardio-load", sync_to_thread=False)
async def chart_cardio_load_data(
    request: Request[Any, Any, Any],
    session: AsyncSession,
    days: Annotated[int, Parameter(ge=1, le=365)] = 30,
) -> dict[str, Any]:
    """Get cardio load data for charts.

    Returns strain, tolerance, and load ratio for the last N days.
    """
    if not is_authenticated(request):
        raise NotAuthorizedException(detail="Authentication required")

    uid = await _connected_user_id(session)
    since_date = date.today() - timedelta(days=days)
    stmt = select(CardioLoad).where(CardioLoad.date >= since_date).order_by(CardioLoad.date.asc())
    if uid:
        stmt = stmt.where(CardioLoad.user_id == uid)
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
    days: Annotated[int, Parameter(ge=1, le=365)] = 30,
) -> Response[bytes] | Redirect:
    """Export sleep data as CSV for the connected user."""
    if not is_authenticated(request):
        return Redirect(path="/admin/login", status_code=HTTP_303_SEE_OTHER)

    # Get connected user to filter by user_id
    connected_user_stmt = select(User).where(User.is_active == True).limit(1)  # noqa: E712
    connected_user_result = await session.execute(connected_user_stmt)
    connected_user = connected_user_result.scalar_one_or_none()

    since_date = date.today() - timedelta(days=days)
    stmt = select(Sleep).where(Sleep.date >= since_date)
    if connected_user:
        stmt = stmt.where(Sleep.user_id == connected_user.polar_user_id)
    stmt = stmt.order_by(Sleep.date.asc())
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
    days: Annotated[int, Parameter(ge=1, le=365)] = 30,
) -> Response[bytes] | Redirect:
    """Export activity data as CSV for the connected user."""
    if not is_authenticated(request):
        return Redirect(path="/admin/login", status_code=HTTP_303_SEE_OTHER)

    # Get connected user to filter by user_id
    connected_user_stmt = select(User).where(User.is_active == True).limit(1)  # noqa: E712
    connected_user_result = await session.execute(connected_user_stmt)
    connected_user = connected_user_result.scalar_one_or_none()

    since_date = date.today() - timedelta(days=days)
    stmt = select(Activity).where(Activity.date >= since_date)
    if connected_user:
        stmt = stmt.where(Activity.user_id == connected_user.polar_user_id)
    stmt = stmt.order_by(Activity.date.asc())
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
    days: Annotated[int, Parameter(ge=1, le=365)] = 30,
) -> Response[bytes] | Redirect:
    """Export recharge/HRV data as CSV for the connected user."""
    if not is_authenticated(request):
        return Redirect(path="/admin/login", status_code=HTTP_303_SEE_OTHER)

    # Get connected user to filter by user_id
    connected_user_stmt = select(User).where(User.is_active == True).limit(1)  # noqa: E712
    connected_user_result = await session.execute(connected_user_stmt)
    connected_user = connected_user_result.scalar_one_or_none()

    since_date = date.today() - timedelta(days=days)
    stmt = select(NightlyRecharge).where(NightlyRecharge.date >= since_date)
    if connected_user:
        stmt = stmt.where(NightlyRecharge.user_id == connected_user.polar_user_id)
    stmt = stmt.order_by(NightlyRecharge.date.asc())
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
    days: Annotated[int, Parameter(ge=1, le=365)] = 30,
) -> Response[bytes] | Redirect:
    """Export cardio load data as CSV for the connected user."""
    if not is_authenticated(request):
        return Redirect(path="/admin/login", status_code=HTTP_303_SEE_OTHER)

    # Get connected user to filter by user_id
    connected_user_stmt = select(User).where(User.is_active == True).limit(1)  # noqa: E712
    connected_user_result = await session.execute(connected_user_stmt)
    connected_user = connected_user_result.scalar_one_or_none()

    since_date = date.today() - timedelta(days=days)
    stmt = select(CardioLoad).where(CardioLoad.date >= since_date)
    if connected_user:
        stmt = stmt.where(CardioLoad.user_id == connected_user.polar_user_id)
    stmt = stmt.order_by(CardioLoad.date.asc())
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
    # MCP connector OAuth consent (auth required via session check)
    oauth_consent_form,
    oauth_consent_submit,
    revoke_oauth_app,
    # API Key management
    admin_regenerate_api_key,
    admin_revoke_api_key,
    admin_create_api_key,
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
