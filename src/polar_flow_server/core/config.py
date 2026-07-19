"""Application configuration."""

import os
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DeploymentMode(str, Enum):
    """Deployment mode for the application."""

    SELF_HOSTED = "self_hosted"
    SAAS = "saas"


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Allow extra env vars without error
    )

    # Deployment
    deployment_mode: DeploymentMode = Field(
        default=DeploymentMode.SELF_HOSTED,
        description="Deployment mode: self_hosted or saas",
    )

    # API
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=8000, description="API port")
    api_prefix: str = Field(default="/api/v1", description="API prefix")

    # Base URL for OAuth callbacks and external links
    # Auto-detected from request if not set, but should be set in production
    base_url: str | None = Field(
        default=None,
        description="Base URL for OAuth callbacks (e.g., https://polar.example.com)",
    )

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://polar:polar@localhost:5432/polar",
        description="PostgreSQL database URL",
    )

    # Security
    api_key: str | None = Field(
        default=None,
        description="Single API key for simple auth (self-hosted mode)",
    )
    encryption_key: str | None = Field(
        default=None,
        description="Encryption key for Polar tokens (base64 encoded)",
    )
    session_secret: str | None = Field(
        default=None,
        description="Secret key for session cookies (auto-generated if not set)",
    )
    jwt_secret: str | None = Field(
        default=None,
        description="JWT secret for authentication (SaaS mode only)",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_expiry_minutes: int = Field(default=15, description="JWT access token expiry")

    # Sync settings
    sync_enabled: bool = Field(
        default=True,
        description="Enable automatic background syncing",
    )
    sync_interval_minutes: int = Field(
        default=60,
        description="How often to run sync cycle (minutes)",
    )
    sync_on_startup: bool = Field(
        default=True,
        description="Sync immediately on startup",
    )
    sync_days_lookback: int = Field(
        default=30,
        description="How many days of data to fetch on sync",
    )
    sync_max_users_per_run: int | None = Field(
        default=None,
        description="Maximum users per sync cycle (None = rate limit aware auto)",
    )
    sync_stagger_seconds: int = Field(
        default=5,
        description="Seconds to wait between user syncs (rate limit protection)",
    )

    # Polar OAuth app credentials (app-level, not user-level)
    # NOTE: For self-hosted, these will be stored in DB via setup wizard
    # For now, support reading from env for testing
    polar_client_id: str | None = Field(
        default=None,
        description="Polar OAuth client ID (from admin.polaraccesslink.com)",
    )
    polar_client_secret: str | None = Field(
        default=None,
        description="Polar OAuth client secret (from admin.polaraccesslink.com)",
    )

    # Self-hosted mode specific
    polar_token_path: Path = Field(
        default=Path.home() / ".polar-flow" / "token",
        description="Path to Polar token file (self-hosted mode)",
    )

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Log level",
    )

    def is_self_hosted(self) -> bool:
        """Check if running in self-hosted mode."""
        return self.deployment_mode == DeploymentMode.SELF_HOSTED

    def is_saas(self) -> bool:
        """Check if running in SaaS mode."""
        return self.deployment_mode == DeploymentMode.SAAS

    def get_encryption_key(self) -> bytes:
        """Get encryption key for Polar tokens.

        In self-hosted mode, generates and persists key to /data/encryption.key
        (or ~/.polar-flow/encryption.key if /data is not writable) to ensure
        tokens survive server restarts.

        Raises:
            ValueError: If encryption key not set in SaaS mode
        """
        import logging

        from cryptography.fernet import Fernet
        from pathlib import Path

        logger = logging.getLogger(__name__)

        if self.encryption_key:
            logger.info("Loaded encryption key from environment")
            return self.encryption_key.encode()

        if self.is_saas():
            raise ValueError("ENCRYPTION_KEY must be set in SaaS mode")

        # Self-hosted: persist key to file so tokens survive restarts
        key_dir = Path("/data")
        if not key_dir.is_dir() or not os.access(key_dir, os.W_OK):
            key_dir = Path.home() / ".polar-flow"
        key_file = key_dir / "encryption.key"
        key_file.parent.mkdir(parents=True, exist_ok=True)

        if key_file.exists():
            logger.info("Loaded encryption key from file", path=str(key_file))
            return key_file.read_bytes().strip()

        # Generate new key and persist
        key = Fernet.generate_key()
        key_file.write_bytes(key)
        key_file.chmod(0o600)  # Owner read/write only
        logger.info("Generated fresh encryption key", path=str(key_file))
        return key

    def get_session_secret(self) -> str:
        """Get session secret for admin cookies.

        In self-hosted mode, generates and persists secret to /data/session.key
        (or ~/.polar-flow/session.key if /data is not writable) to ensure sessions
        survive server restarts.
        """
        import logging
        import secrets
        from pathlib import Path

        logger = logging.getLogger(__name__)

        if self.session_secret:
            logger.info("Loaded session secret from environment")
            return self.session_secret

        # Self-hosted: persist secret to file so sessions survive restarts
        key_dir = Path("/data")
        if not key_dir.is_dir() or not os.access(key_dir, os.W_OK):
            key_dir = Path.home() / ".polar-flow"
        secret_file = key_dir / "session.key"
        secret_file.parent.mkdir(parents=True, exist_ok=True)

        if secret_file.exists():
            logger.info("Loaded session secret from file", path=str(secret_file))
            return secret_file.read_text().strip()

        # Generate new secret and persist
        secret = secrets.token_urlsafe(32)
        secret_file.write_text(secret)
        secret_file.chmod(0o600)  # Owner read/write only
        logger.info("Generated fresh session secret", path=str(secret_file))
        return secret


# Global settings instance
settings = Settings()
