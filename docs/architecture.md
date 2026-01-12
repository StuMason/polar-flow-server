# Architecture

Technical architecture of polar-flow-server.

## System Overview

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Polar API     │────▶│  Sync Service   │────▶│    Database     │
│  (AccessLink)   │     │  (polar-flow)   │     │ (PostgreSQL/    │
└─────────────────┘     └─────────────────┘     │    DuckDB)      │
                                                 └────────┬────────┘
                                                          │
                        ┌─────────────────┐               │
                        │   REST API      │◀──────────────┘
                        │   (Litestar)    │
                        └────────┬────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
              ▼                  ▼                  ▼
        ┌──────────┐      ┌──────────┐      ┌──────────┐
        │Dashboard │      │  Mobile  │      │   MCP    │
        │  (Web)   │      │   App    │      │ (Claude) │
        └──────────┘      └──────────┘      └──────────┘
```

## Components

### Sync Service

Fetches data from Polar AccessLink API using the [polar-flow](https://github.com/StuMason/polar-flow) SDK.

**Responsibilities:**
- Authenticate with Polar API using OAuth2 tokens
- Fetch all data types (sleep, activity, exercises, etc.)
- Transform SDK models to database schemas
- Upsert records (insert or update on conflict)

**Data flow:**
1. SDK fetches JSON from Polar API
2. Pydantic models validate and parse response
3. Transformers convert SDK models to database dicts
4. SQLAlchemy upserts records by unique key

### Transformers

Bridge between SDK models and database schemas. Located in `src/polar_flow_server/transformers/`.

Each transformer:
- Accepts SDK model + user_id
- Returns dict ready for database insertion
- Handles field name mapping (SDK → DB)
- Performs type conversions (timestamps, JSON serialization)

**Example:**
```python
from polar_flow_server.transformers import SleepTransformer

# SDK model from polar-flow
sdk_sleep = await client.sleep.list()

# Transform to database dict
db_dict = SleepTransformer.transform(sdk_sleep[0], user_id="12345")
```

### Database Models

SQLAlchemy 2.0 async models in `src/polar_flow_server/models/`.

**Core tables:**
- `sleep` - Nightly sleep data with stages, HRV, vitals
- `nightly_recharge` - ANS charge, recovery status
- `activity` - Daily steps, calories, active time
- `exercise` - Workouts with duration, distance, HR

**Analytics tables:**
- `cardio_load` - Training strain and tolerance
- `sleepwise_alertness` - Hourly alertness predictions
- `sleepwise_bedtime` - Optimal sleep timing
- `continuous_hr` - Daily heart rate summaries
- `activity_samples` - Minute-by-minute activity

**Biosensing tables:**
- `spo2` - Blood oxygen measurements
- `ecg` - ECG recordings with waveforms
- `body_temperature` - Continuous body temp
- `skin_temperature` - Nightly skin temp

All tables include:
- `id` (auto-increment primary key)
- `user_id` (string, for multi-tenancy)
- `created_at`, `updated_at` (timestamps)

### REST API

Litestar async web framework serving JSON endpoints.

**Structure:**
- `/api/v1/users/{user_id}/...` - User-scoped data endpoints
- `/api/v1/users/{user_id}/sync/trigger` - Manual sync trigger
- `/health` - Health check
- `/admin/...` - Admin dashboard (if enabled)

**Database sessions:**
- Injected via Litestar dependency injection
- Async SQLAlchemy sessions
- Connection pooling via asyncpg (PostgreSQL) or aiosqlite (DuckDB)

## Multi-Tenancy

Every database query is scoped by `user_id`:

```python
stmt = (
    select(Sleep)
    .where(Sleep.user_id == user_id)
    .where(Sleep.date >= since_date)
)
```

**Self-hosted mode:**
- Single user
- `user_id` = Polar API user ID
- DuckDB for simple deployment

**SaaS mode:**
- Multiple users
- `user_id` = Your application's user ID (e.g., Laravel UUID)
- PostgreSQL for production

## Configuration

Environment variables via Pydantic Settings:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Database connection string | `sqlite+aiosqlite:///./data.db` |
| `SYNC_DAYS_LOOKBACK` | Days to sync by default | `28` |
| `POLAR_TOKEN_PATH` | Path to token file | `~/.polar-flow/token` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `ADMIN_ENABLED` | Enable admin dashboard | `false` |

## Tech Stack

- **Framework:** Litestar (async, high-performance)
- **ORM:** SQLAlchemy 2.0 (async)
- **Database:** PostgreSQL (prod) / DuckDB (self-hosted)
- **SDK:** polar-flow (Polar API client)
- **Validation:** Pydantic 2
- **Logging:** structlog (structured JSON logs)
- **Type checking:** mypy strict mode
