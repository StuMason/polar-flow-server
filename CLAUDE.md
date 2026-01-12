# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Self-hosted health analytics server for Polar devices. Syncs data from Polar AccessLink API (9+ endpoints) to PostgreSQL and provides an HTMX-powered admin dashboard plus REST API.

## Development Commands

```bash
# Install dependencies
uv sync --all-extras

# Start PostgreSQL (required for local development)
docker-compose up -d postgres

# Run server with hot reload
uv run uvicorn polar_flow_server.app:app --reload

# Run tests
uv run pytest

# Run single test file
uv run pytest tests/test_api.py

# Run single test function
uv run pytest tests/test_api.py::test_health_check -v

# Type check
uv run mypy src/polar_flow_server

# Lint
uv run ruff check src/

# Lint with auto-fix
uv run ruff check src/ --fix
```

## Architecture

### Stack
- **Litestar** - Async web framework (not FastAPI)
- **SQLAlchemy 2.0** - Async ORM with declarative models
- **PostgreSQL** - Primary database (asyncpg driver)
- **Alembic** - Database migrations (auto-run on container startup)
- **polar-flow SDK** - Polar AccessLink API client
- **HTMX + Tailwind** - Admin UI (server-rendered templates)

### Source Layout (`src/polar_flow_server/`)

```
app.py              # Litestar application factory
routes.py           # Root route (redirects to admin)
core/
  config.py         # Settings via pydantic-settings (reads .env)
  database.py       # SQLAlchemy async engine/session
  auth.py           # API key authentication guard
  security.py       # Token encryption (Fernet)
models/             # SQLAlchemy ORM models
  base.py           # Base class, TimestampMixin, UserScopedMixin
  user.py           # Polar user with encrypted tokens
  sleep.py, activity.py, exercise.py, etc.
transformers/       # SDK model -> DB model mappers
  sleep.py, activity.py, etc.
services/
  sync.py           # SyncService - orchestrates Polar API sync
api/
  health.py         # /health endpoint
  sleep.py          # /users/{user_id}/sleep endpoint
  data.py           # All other data endpoints (activity, recharge, etc.)
  sync.py           # Sync trigger endpoints
admin/
  routes.py         # Admin dashboard, OAuth flow, settings
  auth.py           # Admin user authentication (session-based)
templates/          # Jinja2 templates for admin UI
```

### Key Patterns

**Multi-tenancy**: All data tables include `user_id` column via `UserScopedMixin`. Works for both self-hosted (one user) and SaaS (many users).

**Transformers**: Each Polar SDK model has a corresponding transformer that maps to database model. Located in `transformers/` with consistent interface:
```python
class SleepTransformer:
    @staticmethod
    def transform(sdk_model, user_id: str) -> dict:
        # Returns dict for SQLAlchemy upsert
```

**Sync Service** (`services/sync.py`): Single entry point for syncing all data types. Uses PostgreSQL upsert (ON CONFLICT DO UPDATE) for idempotent syncs.

**Admin Auth**: Session-based authentication for admin panel (separate from API key auth). First-run flow: setup account -> OAuth credentials -> connect Polar.

**API Auth**: Optional API key via `X-API-Key` header. Controlled by `API_KEY` env var. If not set, data endpoints are open.

### Database

- Migrations in `alembic/versions/`
- Create migration: `uv run alembic revision --autogenerate -m "description"`
- Apply migrations: `uv run alembic upgrade head`
- Migrations run automatically in Docker via `docker-entrypoint.sh`

### Configuration

Key environment variables (see `.env.example`):
- `DATABASE_URL` - PostgreSQL connection string
- `DEPLOYMENT_MODE` - `self_hosted` (default) or `saas`
- `API_KEY` - Optional API authentication
- `SYNC_DAYS_LOOKBACK` - Days of historical data to sync (default 30)

Secrets auto-generate in self-hosted mode and persist to `~/.polar-flow/`:
- `encryption.key` - For Polar token encryption
- `session.key` - For admin session cookies

### Testing

Tests use `pytest-asyncio` with auto mode. Test client:
```python
from litestar.testing import AsyncTestClient
from polar_flow_server.app import create_app

client = AsyncTestClient(app=create_app())
```
