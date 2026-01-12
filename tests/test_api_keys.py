"""Tests for per-user API keys functionality."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.core.api_keys import (
    check_rate_limit,
    create_api_key_for_user,
    create_service_key,
    create_temp_auth_code,
    exchange_temp_code,
    generate_api_key,
    generate_temp_code,
    hash_key,
    regenerate_api_key,
    revoke_api_key,
    validate_api_key,
)


class TestKeyGeneration:
    """Tests for API key generation."""

    def test_generate_api_key_format(self):
        """Generated keys should have correct format."""
        key = generate_api_key()

        assert key.raw_key.startswith("pfk_")
        assert len(key.raw_key) == 44  # "pfk_" + 40 hex chars
        assert len(key.key_hash) == 64  # SHA-256 hex
        assert key.key_prefix == key.raw_key[:12]

    def test_generate_api_key_uniqueness(self):
        """Each generated key should be unique."""
        keys = [generate_api_key() for _ in range(100)]
        raw_keys = [k.raw_key for k in keys]
        hashes = [k.key_hash for k in keys]

        assert len(set(raw_keys)) == 100
        assert len(set(hashes)) == 100

    def test_generate_temp_code_format(self):
        """Generated temp codes should have correct format."""
        code = generate_temp_code()

        assert code.raw_code.startswith("temp_")
        assert len(code.raw_code) == 69  # "temp_" + 64 hex chars
        assert len(code.code_hash) == 64  # SHA-256 hex

    def test_hash_key_consistency(self):
        """Same key should always produce same hash."""
        key = "pfk_test123456789"
        hash1 = hash_key(key)
        hash2 = hash_key(key)

        assert hash1 == hash2

    def test_hash_key_different_keys(self):
        """Different keys should produce different hashes."""
        hash1 = hash_key("pfk_key1")
        hash2 = hash_key("pfk_key2")

        assert hash1 != hash2


class TestApiKeyCreation:
    """Tests for API key creation in database."""

    @pytest.mark.asyncio
    async def test_create_user_api_key(self, async_session: AsyncSession, test_user):
        """Should create a user-scoped API key."""
        api_key, raw_key = await create_api_key_for_user(
            user_id=test_user.polar_user_id,
            name="My Key",
            session=async_session,
        )

        assert api_key.user_id == test_user.polar_user_id
        assert api_key.name == "My Key"
        assert api_key.is_active is True
        assert api_key.rate_limit_requests == 1000
        assert raw_key.startswith("pfk_")

    @pytest.mark.asyncio
    async def test_create_service_key(self, async_session: AsyncSession):
        """Should create a service-level API key."""
        api_key, raw_key = await create_service_key(
            name="Service Key",
            session=async_session,
        )

        assert api_key.user_id is None
        assert api_key.is_service_level is True
        assert api_key.name == "Service Key"
        assert raw_key.startswith("pfk_")

    @pytest.mark.asyncio
    async def test_create_key_with_custom_rate_limit(self, async_session: AsyncSession, test_user):
        """Should respect custom rate limit."""
        api_key, _ = await create_api_key_for_user(
            user_id=test_user.polar_user_id,
            name="Limited Key",
            session=async_session,
            rate_limit=100,
        )

        assert api_key.rate_limit_requests == 100
        assert api_key.rate_limit_remaining == 100


class TestApiKeyValidation:
    """Tests for API key validation."""

    @pytest.mark.asyncio
    async def test_validate_valid_key(self, async_session: AsyncSession, user_api_key):
        """Should validate a valid API key."""
        api_key, raw_key = user_api_key

        validated = await validate_api_key(raw_key, async_session)

        assert validated is not None
        assert validated.id == api_key.id

    @pytest.mark.asyncio
    async def test_validate_invalid_key(self, async_session: AsyncSession):
        """Should reject an invalid API key."""
        validated = await validate_api_key("pfk_invalid_key_12345", async_session)

        assert validated is None

    @pytest.mark.asyncio
    async def test_validate_inactive_key(self, async_session: AsyncSession, user_api_key):
        """Should reject an inactive API key."""
        api_key, raw_key = user_api_key

        # Deactivate the key
        api_key.is_active = False
        await async_session.commit()

        validated = await validate_api_key(raw_key, async_session)

        assert validated is None


class TestRateLimiting:
    """Tests for rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_rate_limit_decrement(self, async_session: AsyncSession, user_api_key):
        """Rate limit should decrement on each check."""
        api_key, _ = user_api_key

        is_allowed, info = await check_rate_limit(api_key)

        assert is_allowed is True
        assert info["remaining"] == 999
        assert api_key.rate_limit_remaining == 999

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self, async_session: AsyncSession, user_api_key):
        """Should reject when rate limit exceeded."""
        api_key, _ = user_api_key

        # Exhaust the rate limit with a future reset time
        api_key.rate_limit_remaining = 0
        api_key.rate_limit_reset_at = datetime.now(UTC) + timedelta(hours=1)
        await async_session.commit()

        is_allowed, info = await check_rate_limit(api_key)

        assert is_allowed is False
        assert info["remaining"] == 0

    @pytest.mark.asyncio
    async def test_rate_limit_reset(self, async_session: AsyncSession, user_api_key):
        """Rate limit should reset after window expires."""
        api_key, _ = user_api_key

        # Set remaining to 0 with expired reset time
        api_key.rate_limit_remaining = 0
        api_key.rate_limit_reset_at = datetime.now(UTC) - timedelta(hours=1)
        await async_session.commit()

        is_allowed, info = await check_rate_limit(api_key)

        assert is_allowed is True
        assert api_key.rate_limit_remaining == 999  # Reset to 1000, then decremented


class TestTempCodeExchange:
    """Tests for temporary code exchange flow."""

    @pytest.mark.asyncio
    async def test_exchange_valid_code(self, async_session: AsyncSession, temp_auth_code):
        """Should exchange a valid temp code."""
        temp_code, raw_code = temp_auth_code

        result = await exchange_temp_code(
            raw_code=raw_code,
            session=async_session,
            expected_client_id="test_client",
        )

        assert result is not None
        assert result.user_id == temp_code.user_id
        assert result.is_used is True

    @pytest.mark.asyncio
    async def test_exchange_invalid_code(self, async_session: AsyncSession):
        """Should reject an invalid temp code."""
        result = await exchange_temp_code(
            raw_code="temp_invalid_code_12345",
            session=async_session,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_exchange_used_code(self, async_session: AsyncSession, temp_auth_code):
        """Should reject an already-used temp code."""
        temp_code, raw_code = temp_auth_code

        # First exchange should work
        result1 = await exchange_temp_code(raw_code, async_session)
        assert result1 is not None

        # Second exchange should fail
        result2 = await exchange_temp_code(raw_code, async_session)
        assert result2 is None

    @pytest.mark.asyncio
    async def test_exchange_expired_code(self, async_session: AsyncSession, test_user):
        """Should reject an expired temp code."""
        # Create an expired code manually
        temp_code, raw_code = await create_temp_auth_code(
            user_id=test_user.polar_user_id,
            session=async_session,
        )
        temp_code.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await async_session.commit()

        result = await exchange_temp_code(raw_code, async_session)

        assert result is None

    @pytest.mark.asyncio
    async def test_exchange_wrong_client_id(self, async_session: AsyncSession, temp_auth_code):
        """Should reject code with wrong client_id."""
        _, raw_code = temp_auth_code

        result = await exchange_temp_code(
            raw_code=raw_code,
            session=async_session,
            expected_client_id="wrong_client",
        )

        assert result is None


class TestKeyManagement:
    """Tests for key regeneration and revocation."""

    @pytest.mark.asyncio
    async def test_regenerate_key(self, async_session: AsyncSession, user_api_key):
        """Should regenerate a key with new hash."""
        api_key, old_raw_key = user_api_key
        old_hash = api_key.key_hash

        new_raw_key = await regenerate_api_key(api_key, async_session)

        assert new_raw_key != old_raw_key
        assert api_key.key_hash != old_hash
        assert api_key.is_active is True

    @pytest.mark.asyncio
    async def test_regenerate_resets_rate_limit(self, async_session: AsyncSession, user_api_key):
        """Regeneration should reset rate limits."""
        api_key, _ = user_api_key

        # Partially exhaust rate limit
        api_key.rate_limit_remaining = 500
        await async_session.commit()

        await regenerate_api_key(api_key, async_session)

        assert api_key.rate_limit_remaining == api_key.rate_limit_requests

    @pytest.mark.asyncio
    async def test_revoke_key(self, async_session: AsyncSession, user_api_key):
        """Should revoke (deactivate) a key."""
        api_key, raw_key = user_api_key

        await revoke_api_key(api_key, async_session)

        assert api_key.is_active is False

        # Validation should fail
        validated = await validate_api_key(raw_key, async_session)
        assert validated is None


class TestUserScoping:
    """Tests for user-scoped key access control."""

    @pytest.mark.asyncio
    async def test_user_scoped_key_properties(self, async_session: AsyncSession, user_api_key):
        """User-scoped key should have correct properties."""
        api_key, _ = user_api_key

        assert api_key.is_user_scoped is True
        assert api_key.is_service_level is False
        assert api_key.user_id is not None

    @pytest.mark.asyncio
    async def test_service_key_properties(self, async_session: AsyncSession, service_api_key):
        """Service key should have correct properties."""
        api_key, _ = service_api_key

        assert api_key.is_user_scoped is False
        assert api_key.is_service_level is True
        assert api_key.user_id is None
