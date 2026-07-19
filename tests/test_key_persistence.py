"""Tests for encryption/session key persistence (issue #50).

Covers: key generation + reuse under KEY_DIR, env-var override, migration
from the legacy ~/.polar-flow location, generation warnings, and the startup
check that detects an encryption-key/stored-token mismatch.
"""

import logging

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.core.config import Settings


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Point HOME at a temp dir so tests never touch the real ~/.polar-flow."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


class TestEncryptionKeyPersistence:
    def test_generates_and_persists_key(self, tmp_path, isolated_home):
        settings = Settings(key_dir=tmp_path / "keys")
        key = settings.get_encryption_key()

        key_file = tmp_path / "keys" / "encryption.key"
        assert key_file.exists()
        assert key_file.read_bytes().strip() == key
        assert key_file.stat().st_mode & 0o777 == 0o600
        # Must be a valid Fernet key
        Fernet(key)

    def test_reuses_existing_key(self, tmp_path, isolated_home):
        settings = Settings(key_dir=tmp_path / "keys")
        first = settings.get_encryption_key()
        second = Settings(key_dir=tmp_path / "keys").get_encryption_key()
        assert first == second

    def test_env_override_wins(self, tmp_path, isolated_home):
        explicit = Fernet.generate_key().decode()
        settings = Settings(key_dir=tmp_path / "keys", encryption_key=explicit)
        assert settings.get_encryption_key() == explicit.encode()
        # Nothing written to disk when the key comes from config
        assert not (tmp_path / "keys" / "encryption.key").exists()

    def test_migrates_key_from_legacy_location(self, tmp_path, isolated_home):
        legacy_dir = isolated_home / ".polar-flow"
        legacy_dir.mkdir()
        legacy_key = Fernet.generate_key()
        (legacy_dir / "encryption.key").write_bytes(legacy_key)

        settings = Settings(key_dir=tmp_path / "new-keys")
        assert settings.get_encryption_key() == legacy_key
        # Copied to the new location for future reads
        assert (tmp_path / "new-keys" / "encryption.key").read_bytes() == legacy_key

    def test_default_key_dir_is_home_no_migration_noise(self, isolated_home):
        # Default key_dir == legacy path: generation works, no self-migration
        settings = Settings()
        key = settings.get_encryption_key()
        assert (isolated_home / ".polar-flow" / "encryption.key").read_bytes().strip() == key

    def test_warns_on_fresh_generation(self, tmp_path, isolated_home, caplog):
        settings = Settings(key_dir=tmp_path / "keys")
        with caplog.at_level(logging.WARNING, logger="polar_flow_server.core.config"):
            settings.get_encryption_key()
        assert any("NEW token encryption key" in r.message for r in caplog.records)

        # Reuse must NOT warn
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="polar_flow_server.core.config"):
            Settings(key_dir=tmp_path / "keys").get_encryption_key()
        assert not caplog.records


class TestSessionSecretPersistence:
    def test_generates_and_persists_secret(self, tmp_path, isolated_home):
        settings = Settings(key_dir=tmp_path / "keys")
        secret = settings.get_session_secret()
        secret_file = tmp_path / "keys" / "session.key"
        assert secret_file.read_text().strip() == secret
        assert secret_file.stat().st_mode & 0o777 == 0o600
        assert Settings(key_dir=tmp_path / "keys").get_session_secret() == secret

    def test_env_override_wins(self, tmp_path, isolated_home):
        settings = Settings(key_dir=tmp_path / "keys", session_secret="explicit-secret")
        assert settings.get_session_secret() == "explicit-secret"
        assert not (tmp_path / "keys" / "session.key").exists()

    def test_migrates_secret_from_legacy_location(self, tmp_path, isolated_home):
        legacy_dir = isolated_home / ".polar-flow"
        legacy_dir.mkdir()
        (legacy_dir / "session.key").write_text("legacy-secret\n")

        settings = Settings(key_dir=tmp_path / "new-keys")
        assert settings.get_session_secret() == "legacy-secret"


class TestStartupTokenCheck:
    async def _add_user(self, session: AsyncSession, encrypted: str) -> None:
        from polar_flow_server.models.user import User

        session.add(
            User(
                id="key-check-user",
                polar_user_id="polar_key_check",
                access_token_encrypted=encrypted,
                is_active=True,
            )
        )
        await session.commit()

    async def test_healthy_when_no_users(self, async_session: AsyncSession):
        from polar_flow_server.core.security import verify_stored_tokens_decryptable

        assert await verify_stored_tokens_decryptable(async_session) is True

    async def test_healthy_when_tokens_decrypt(self, async_session: AsyncSession):
        from polar_flow_server.core.security import (
            token_encryption,
            verify_stored_tokens_decryptable,
        )

        await self._add_user(async_session, token_encryption.encrypt("real-token"))
        assert await verify_stored_tokens_decryptable(async_session) is True

    async def test_critical_log_on_key_mismatch(self, async_session: AsyncSession, caplog):
        from polar_flow_server.core.security import verify_stored_tokens_decryptable

        # Token encrypted with a DIFFERENT key than the current global cipher
        other_cipher = Fernet(Fernet.generate_key())
        await self._add_user(async_session, other_cipher.encrypt(b"real-token").decode())

        with caplog.at_level(logging.CRITICAL, logger="polar_flow_server.core.security"):
            assert await verify_stored_tokens_decryptable(async_session) is False
        assert any("ENCRYPTION KEY MISMATCH" in r.message for r in caplog.records)
