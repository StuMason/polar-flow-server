"""Alembic migration environment configuration."""

from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy import create_engine

from alembic import context

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import settings for database URL
from polar_flow_server.core.config import settings

# Import Base and all models to register them with metadata
from polar_flow_server.models.base import Base
from polar_flow_server.models import (  # noqa: F401
    Activity,
    ActivitySamples,
    APIKey,
    AppSettings,
    BodyTemperature,
    CardioLoad,
    ContinuousHeartRate,
    ECG,
    Exercise,
    NightlyRecharge,
    SkinTemperature,
    Sleep,
    SleepWiseAlertness,
    SleepWiseBedtime,
    SpO2,
    User,
)

# Set target metadata for autogenerate support
target_metadata = Base.metadata


def get_sync_database_url() -> str:
    """Get synchronous database URL for migrations.

    Converts asyncpg URL to psycopg for sync operations.
    """
    url = settings.database_url

    # Replace async driver with sync driver for migrations
    if "+asyncpg" in url:
        url = url.replace("+asyncpg", "+psycopg")

    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = get_sync_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with a connection."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    url = get_sync_database_url()

    connectable = create_engine(
        url,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
