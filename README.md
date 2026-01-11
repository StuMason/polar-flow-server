# polar-flow-server

Self-hosted health analytics server for Polar devices. Own your data, analyze it yourself.

## What This Does

Polar devices collect health data: sleep, HRV, activity, exercises. The Polar API provides access to this data, but only for the last 28-30 days.

This server:

1. Syncs all 9 Polar API endpoints automatically
2. Stores everything in PostgreSQL (your data, your server)
3. Provides an HTMX-powered admin dashboard
4. Exposes REST API for custom integrations
5. Multi-user ready (same codebase for self-hosted and SaaS)

## Architecture

```
Polar API → polar-flow SDK → Sync Service → PostgreSQL
                                                  ↓
                                           Admin Dashboard (HTMX)
                                                  ↓
                                             REST API
```

**Stack:**
- Litestar (async web framework)
- SQLAlchemy 2.0 (async ORM)
- PostgreSQL
- HTMX + Tailwind (admin UI)
- polar-flow SDK v1.3.0

## Quick Start

### 1. Get Polar API Credentials

1. Go to [admin.polaraccesslink.com](https://admin.polaraccesslink.com)
2. Create a new client
3. Set redirect URI to `http://localhost:8000/admin/oauth/callback`
4. Note your `CLIENT_ID` and `CLIENT_SECRET`

### 2. Start with Docker Compose

```bash
git clone https://github.com/StuMason/polar-flow-server.git
cd polar-flow-server
docker-compose up -d
```

### 3. Connect Your Polar Account

1. Open http://localhost:8000/admin
2. Enter your Polar OAuth credentials
3. Click "Connect with Polar" to authorize
4. Hit "Sync Now" to pull your data

The server syncs data every hour automatically.

## Dashboard

The admin panel at `/admin/dashboard` shows:

- **Key Metrics** - HRV, Heart Rate, Training Strain, Alertness, Sleep Score
- **Record Counts** - All 9 data types with totals
- **Recent Sleep** - Last 7 days with scores
- **Nightly Recharge** - HRV, ANS charge, recovery status
- **Training Load** - Strain, tolerance, load ratio
- **Continuous HR** - Daily min/avg/max heart rate

## Data Synced (9 Endpoints)

| Endpoint | Data |
|----------|------|
| **Sleep** | Score, stages (light/deep/REM), duration |
| **Nightly Recharge** | HRV, ANS charge, recovery status |
| **Daily Activity** | Steps, distance, calories, active time |
| **Exercises** | Sport, duration, HR zones, training load |
| **Cardio Load** | Strain, tolerance, load ratio, status |
| **SleepWise Alertness** | Hourly alertness predictions |
| **SleepWise Bedtime** | Optimal sleep timing recommendations |
| **Activity Samples** | Minute-by-minute step data |
| **Continuous HR** | All-day heart rate (5-min intervals) |

## Configuration

Environment variables (see `.env.example`):

```bash
# Database
DATABASE_URL=postgresql+asyncpg://polar:polar@postgres:5432/polar

# Deployment mode
DEPLOYMENT_MODE=self_hosted

# Sync settings
SYNC_INTERVAL_HOURS=1
SYNC_ON_STARTUP=false
SYNC_DAYS_LOOKBACK=28

# Optional: Set explicit encryption key (auto-generated otherwise)
# ENCRYPTION_KEY=your-32-byte-fernet-key
```

## API Endpoints

```bash
# Health check
curl http://localhost:8000/health

# Get sleep data (last 7 days)
curl "http://localhost:8000/api/users/{user_id}/sleep?days=7"

# Get sleep for specific date
curl "http://localhost:8000/api/users/{user_id}/sleep/2026-01-10"

# Trigger manual sync (via admin panel recommended)
curl -X POST http://localhost:8000/admin/sync
```

## Development

```bash
# Install dependencies
uv sync --all-extras

# Start PostgreSQL
docker-compose up -d postgres

# Run server with hot reload
uv run uvicorn polar_flow_server.app:app --reload

# Run tests
uv run pytest

# Type check
uv run mypy src/polar_flow_server

# Lint
uv run ruff check src/
```

## Multi-Tenancy

The server supports multiple users out of the box:

- Every table includes `user_id` column
- All queries scoped by `user_id`
- Self-hosted: typically one user
- SaaS: many users, same codebase

For SaaS deployment, set `DEPLOYMENT_MODE=saas` and provide `ENCRYPTION_KEY`.

## Built With

- [polar-flow](https://github.com/StuMason/polar-flow) - Python SDK for Polar AccessLink API
- [Litestar](https://litestar.dev/) - Async web framework
- [SQLAlchemy](https://www.sqlalchemy.org/) - Async ORM
- [HTMX](https://htmx.org/) - Admin UI interactions
- [Tailwind CSS](https://tailwindcss.com/) - Styling

## License

MIT
