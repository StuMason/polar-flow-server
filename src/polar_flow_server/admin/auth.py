"""Admin authentication for dashboard access.

Security Model:
- Admin users stored in database with Argon2 hashed passwords
- Server-side sessions (not JWT) for simplicity and security
- Sessions stored in memory (use Redis for multi-instance deployments)
- Session cookie is HTTP-only and secure in production
"""

from datetime import UTC, datetime
from typing import Any

from litestar.connection import ASGIConnection
from litestar.exceptions import NotAuthorizedException
from litestar.handlers import BaseRouteHandler
from litestar.response import Redirect
from litestar.status_codes import HTTP_303_SEE_OTHER
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.core.password import hash_password, verify_password
from polar_flow_server.models.admin_user import AdminUser


async def admin_user_exists(session: AsyncSession) -> bool:
    """Check if any admin user exists in the database.

    Args:
        session: Database session

    Returns:
        True if at least one admin user exists
    """
    result = await session.execute(select(func.count(AdminUser.id)))
    count = result.scalar() or 0
    return count > 0


async def get_admin_by_email(email: str, session: AsyncSession) -> AdminUser | None:
    """Get admin user by email.

    Args:
        email: Email address to look up
        session: Database session

    Returns:
        AdminUser if found, None otherwise
    """
    result = await session.execute(
        select(AdminUser).where(AdminUser.email == email, AdminUser.is_active == True)  # noqa: E712
    )
    return result.scalar_one_or_none()


async def authenticate_admin(email: str, password: str, session: AsyncSession) -> AdminUser | None:
    """Authenticate admin user with email and password.

    Uses constant-time comparison via Argon2 to prevent timing attacks.

    Args:
        email: Admin email
        password: Plain text password
        session: Database session

    Returns:
        AdminUser if authentication successful, None otherwise
    """
    admin = await get_admin_by_email(email, session)
    if not admin:
        # Still hash something to prevent timing attacks
        hash_password("dummy_password_to_prevent_timing_attack")
        return None

    if not verify_password(password, admin.password_hash):
        return None

    # Update last login time
    admin.last_login_at = datetime.now(UTC)
    await session.commit()

    return admin


async def create_admin_user(
    email: str,
    password: str,
    session: AsyncSession,
    name: str | None = None,
) -> AdminUser:
    """Create a new admin user.

    Args:
        email: Admin email (must be unique)
        password: Plain text password (will be hashed)
        session: Database session
        name: Optional display name

    Returns:
        Created AdminUser

    Raises:
        ValueError: If email already exists
    """
    # Check if email already exists
    existing = await get_admin_by_email(email, session)
    if existing:
        raise ValueError(f"Admin user with email {email} already exists")

    admin = AdminUser(
        email=email,
        password_hash=hash_password(password),
        name=name,
    )
    session.add(admin)
    await session.commit()
    await session.refresh(admin)

    return admin


def is_authenticated(connection: ASGIConnection[Any, Any, Any, Any]) -> bool:
    """Check if the current request has an authenticated admin session.

    Args:
        connection: The ASGI connection

    Returns:
        True if authenticated, False otherwise
    """
    session_data = connection.session
    return session_data.get("admin_id") is not None


async def require_admin_auth(
    connection: ASGIConnection[Any, Any, Any, Any], _: BaseRouteHandler
) -> None:
    """Guard that requires admin authentication.

    Use this guard on routes that should only be accessible to logged-in admins.

    Raises:
        NotAuthorizedException: If not authenticated (will redirect to login)
    """
    if not is_authenticated(connection):
        # For API endpoints, return 401
        # For browser requests, redirect to login
        accept = connection.headers.get("accept", "")
        if "text/html" in accept:
            raise NotAuthorizedException(
                detail="Authentication required",
                extra={"redirect_to": "/admin/login"},
            )
        raise NotAuthorizedException(detail="Authentication required")


def login_admin(connection: ASGIConnection[Any, Any, Any, Any], admin: AdminUser) -> None:
    """Set up authenticated session for admin.

    Args:
        connection: The ASGI connection
        admin: The authenticated admin user
    """
    connection.session["admin_id"] = admin.id
    connection.session["admin_email"] = admin.email


def logout_admin(connection: ASGIConnection[Any, Any, Any, Any]) -> None:
    """Clear admin session.

    Args:
        connection: The ASGI connection
    """
    connection.session.clear()


def get_redirect_for_unauthenticated() -> Redirect:
    """Get redirect response to login page.

    Returns:
        Redirect to /admin/login
    """
    return Redirect(path="/admin/login", status_code=HTTP_303_SEE_OTHER)
