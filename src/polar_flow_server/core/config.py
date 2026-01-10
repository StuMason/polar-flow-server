"""Application configuration."""

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

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://polar:polar@localhost:5432/polar",
        description="PostgreSQL database URL",
    )

    # Security
    encryption_key: str | None = Field(
        default=None,
        description="Encryption key for Polar tokens (base64 encoded)",
    )
    jwt_secret: str | None = Field(
        default=None,
        description="JWT secret for authentication (SaaS mode only)",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_expiry_minutes: int = Field(default=15, description="JWT access token expiry")

    # Sync settings
    sync_interval_hours: int = Field(default=1, description="How often to sync data")
    sync_on_startup: bool = Field(default=True, description="Sync immediately on startup")
    sync_days_lookback: int = Field(
        default=30,
        description="How many days of data to fetch on sync",
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

        Raises:
            ValueError: If encryption key not set in SaaS mode
        """
        if self.encryption_key:
            return self.encryption_key.encode()

        if self.is_saas():
            raise ValueError("ENCRYPTION_KEY must be set in SaaS mode")

        # Generate a default key for self-hosted mode (not secure for production SaaS)
        from cryptography.fernet import Fernet

        return Fernet.generate_key()


# Global settings instance
settings = Settings()
