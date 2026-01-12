"""API key generation, validation, and rate limiting utilities."""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.models.api_key import APIKey
from polar_flow_server.models.temp_auth_code import TempAuthCode

# Key format: pfk_<40 random alphanumeric chars>
KEY_PREFIX = "pfk_"
KEY_RANDOM_LENGTH = 40
TEMP_CODE_PREFIX = "temp_"
TEMP_CODE_LENGTH = 64

# Rate limiting defaults
DEFAULT_RATE_LIMIT = 1000  # requests per hour
RATE_LIMIT_WINDOW_HOURS = 1


class GeneratedKey(NamedTuple):
    """Result of generating a new API key."""

    raw_key: str  # Full key (only shown once)
    key_hash: str  # SHA-256 hash for storage
    key_prefix: str  # First 8 chars for identification


class GeneratedTempCode(NamedTuple):
    """Result of generating a temporary auth code."""

    raw_code: str  # Full code (passed to client)
    code_hash: str  # SHA-256 hash for storage


def generate_api_key() -> GeneratedKey:
    """Generate a new API key.

    Returns:
        GeneratedKey with raw_key, key_hash, and key_prefix

    Example:
        >>> key = generate_api_key()
        >>> key.raw_key
        'pfk_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0'
        >>> key.key_prefix
        'pfk_a1b2'
    """
    # Generate random alphanumeric string
    random_part = secrets.token_hex(KEY_RANDOM_LENGTH // 2)  # hex = 2 chars per byte
    raw_key = f"{KEY_PREFIX}{random_part}"

    # Hash for storage
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    # Prefix for identification (first 8 chars after pfk_)
    key_prefix = raw_key[:12]  # "pfk_" + first 8 chars

    return GeneratedKey(raw_key=raw_key, key_hash=key_hash, key_prefix=key_prefix)


def generate_temp_code() -> GeneratedTempCode:
    """Generate a temporary authorization code for OAuth exchange.

    Returns:
        GeneratedTempCode with raw_code and code_hash
    """
    random_part = secrets.token_hex(TEMP_CODE_LENGTH // 2)
    raw_code = f"{TEMP_CODE_PREFIX}{random_part}"
    code_hash = hashlib.sha256(raw_code.encode()).hexdigest()

    return GeneratedTempCode(raw_code=raw_code, code_hash=code_hash)


def hash_key(raw_key: str) -> str:
    """Hash an API key for lookup.

    Args:
        raw_key: The raw API key string

    Returns:
        SHA-256 hash of the key
    """
    return hashlib.sha256(raw_key.encode()).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    """Compare two strings in constant time to prevent timing attacks.

    Args:
        a: First string
        b: Second string

    Returns:
        True if strings are equal
    """
    return hmac.compare_digest(a.encode(), b.encode())


async def get_api_key_by_hash(key_hash: str, session: AsyncSession) -> APIKey | None:
    """Look up an API key by its hash.

    Args:
        key_hash: SHA-256 hash of the key
        session: Database session

    Returns:
        APIKey if found, None otherwise
    """
    result = await session.execute(select(APIKey).where(APIKey.key_hash == key_hash))
    return result.scalar_one_or_none()


async def validate_api_key(raw_key: str, session: AsyncSession) -> APIKey | None:
    """Validate an API key and return the record if valid.

    Args:
        raw_key: The raw API key string
        session: Database session

    Returns:
        APIKey if valid and active, None otherwise
    """
    key_hash = hash_key(raw_key)
    api_key = await get_api_key_by_hash(key_hash, session)

    if api_key is None or not api_key.is_active:
        return None

    return api_key


async def check_rate_limit(api_key: APIKey) -> tuple[bool, dict[str, int]]:
    """Check if the API key is within its rate limit.

    Updates the rate limit counters on the APIKey object.
    Caller must commit the session to persist changes.

    Args:
        api_key: The API key to check

    Returns:
        Tuple of (is_allowed, rate_limit_info)
        rate_limit_info contains: limit, remaining, reset (unix timestamp)
    """
    now = datetime.now(UTC)

    # Reset if window expired
    if api_key.rate_limit_reset_at is None or now >= api_key.rate_limit_reset_at:
        api_key.rate_limit_remaining = api_key.rate_limit_requests
        api_key.rate_limit_reset_at = now + timedelta(hours=RATE_LIMIT_WINDOW_HOURS)

    # Build rate limit info
    reset_timestamp = int(api_key.rate_limit_reset_at.timestamp())
    rate_limit_info = {
        "limit": api_key.rate_limit_requests,
        "remaining": max(0, api_key.rate_limit_remaining),
        "reset": reset_timestamp,
    }

    # Check limit
    if api_key.rate_limit_remaining <= 0:
        return False, rate_limit_info

    # Decrement
    api_key.rate_limit_remaining -= 1
    rate_limit_info["remaining"] = api_key.rate_limit_remaining

    return True, rate_limit_info


async def create_api_key_for_user(
    user_id: str,
    name: str,
    session: AsyncSession,
    rate_limit: int = DEFAULT_RATE_LIMIT,
) -> tuple[APIKey, str]:
    """Create a new API key for a user.

    Args:
        user_id: The user's polar_user_id
        name: Human-readable name for the key
        session: Database session
        rate_limit: Requests per hour (default: 1000)

    Returns:
        Tuple of (APIKey record, raw_key)
        The raw_key should be shown to the user ONCE
    """
    generated = generate_api_key()

    api_key = APIKey(
        key_hash=generated.key_hash,
        key_prefix=generated.key_prefix,
        name=name,
        user_id=user_id,
        is_active=True,
        rate_limit_requests=rate_limit,
        rate_limit_remaining=rate_limit,
    )

    session.add(api_key)
    await session.flush()  # Get the ID

    return api_key, generated.raw_key


async def create_service_key(
    name: str,
    session: AsyncSession,
    rate_limit: int = DEFAULT_RATE_LIMIT,
) -> tuple[APIKey, str]:
    """Create a new service-level API key (full access).

    Args:
        name: Human-readable name for the key
        session: Database session
        rate_limit: Requests per hour (default: 1000)

    Returns:
        Tuple of (APIKey record, raw_key)
    """
    generated = generate_api_key()

    api_key = APIKey(
        key_hash=generated.key_hash,
        key_prefix=generated.key_prefix,
        name=name,
        user_id=None,  # Service-level key
        is_active=True,
        rate_limit_requests=rate_limit,
        rate_limit_remaining=rate_limit,
    )

    session.add(api_key)
    await session.flush()

    return api_key, generated.raw_key


async def regenerate_api_key(api_key: APIKey, session: AsyncSession) -> str:
    """Regenerate an API key (invalidate old, create new hash).

    Args:
        api_key: The existing API key to regenerate
        session: Database session

    Returns:
        The new raw key (shown once)
    """
    generated = generate_api_key()

    api_key.key_hash = generated.key_hash
    api_key.key_prefix = generated.key_prefix
    api_key.created_at = datetime.now(UTC)
    api_key.last_used_at = None
    # Reset rate limits
    api_key.rate_limit_remaining = api_key.rate_limit_requests
    api_key.rate_limit_reset_at = None

    await session.flush()

    return generated.raw_key


async def revoke_api_key(api_key: APIKey, session: AsyncSession) -> None:
    """Revoke an API key (mark as inactive).

    Args:
        api_key: The API key to revoke
        session: Database session
    """
    api_key.is_active = False
    await session.flush()


async def create_temp_auth_code(
    user_id: str,
    session: AsyncSession,
    client_id: str | None = None,
) -> tuple[TempAuthCode, str]:
    """Create a temporary auth code for OAuth exchange.

    Args:
        user_id: The user's polar_user_id
        session: Database session
        client_id: Optional client identifier

    Returns:
        Tuple of (TempAuthCode record, raw_code)
    """
    generated = generate_temp_code()

    temp_code = TempAuthCode(
        code_hash=generated.code_hash,
        user_id=user_id,
        client_id=client_id,
        is_used=False,
        expires_at=TempAuthCode.calculate_expiry(),
    )

    session.add(temp_code)
    await session.flush()

    return temp_code, generated.raw_code


async def exchange_temp_code(
    raw_code: str,
    session: AsyncSession,
    expected_client_id: str | None = None,
) -> TempAuthCode | None:
    """Exchange a temporary code (validate and mark as used).

    Args:
        raw_code: The raw temporary code
        session: Database session
        expected_client_id: If provided, validate against stored client_id

    Returns:
        TempAuthCode if valid, None otherwise
    """
    code_hash = hashlib.sha256(raw_code.encode()).hexdigest()

    result = await session.execute(select(TempAuthCode).where(TempAuthCode.code_hash == code_hash))
    temp_code = result.scalar_one_or_none()

    if temp_code is None:
        return None

    # Check validity
    if not temp_code.is_valid:
        return None

    # Check client_id if provided
    if expected_client_id is not None and temp_code.client_id != expected_client_id:
        return None

    # Mark as used
    temp_code.is_used = True
    await session.flush()

    return temp_code


async def cleanup_expired_temp_codes(session: AsyncSession) -> int:
    """Delete expired temporary auth codes.

    Args:
        session: Database session

    Returns:
        Number of codes deleted
    """
    from sqlalchemy import delete
    from sqlalchemy.engine import CursorResult

    now = datetime.now(UTC)
    result = await session.execute(
        delete(TempAuthCode).where(TempAuthCode.expires_at < now)
    )
    # Cast to CursorResult which has rowcount attribute
    cursor_result: CursorResult[tuple[()]] = result  # type: ignore[assignment]
    return cursor_result.rowcount or 0
