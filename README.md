# polar-flow-server

Self-hosted health analytics server for Polar devices. Own your data, analyze it yourself.

## What This Does

Polar devices collect health data: sleep, HRV, activity, exercises. The Polar API provides access to this data, but only for the last 28-30 days.

This server:

1. Syncs data from Polar API automatically
2. Stores everything in PostgreSQL (your data, your server)
3. Runs analytics (HRV baselines, recovery scores, sleep debt)
4. Exposes REST API for dashboards and integrations
5. Multi-user ready (same codebase for self-hosted and SaaS)

## Architecture

```
Polar API → polar-flow SDK → Sync Service → PostgreSQL → Analytics → REST API
                                                                          ↓
                                                                Laravel/Dashboard
```

**Python data analytics engine:**
- Litestar (async web framework)
- SQLAlchemy 2.0 (async ORM)
- PostgreSQL (self-hosted or shared with Laravel)
- Polars (data processing)
- Strict type checking with mypy

**Multi-tenancy:**
- Every table includes `user_id` column
- All API endpoints scoped by `user_id`
- Self-hosted: one user, SaaS: many users
- Same codebase for both modes

## Quick Start

### 1. Get Polar API Credentials

1. Go to [admin.polaraccesslink.com](https://admin.polaraccesslink.com)
2. Create a new client
3. Set redirect URI to `http://localhost:8888/callback`
4. Note your `CLIENT_ID` and `CLIENT_SECRET`

### 2. Authenticate with Polar

```bash
# Authenticate to get your token
docker run -it --rm \
  -e CLIENT_ID=your_client_id \
  -e CLIENT_SECRET=your_client_secret \
  -v ~/.polar-flow:/root/.polar-flow \
  ghcr.io/stumason/polar-flow-server:latest \
  polar-flow auth
```

### 3. Start with Docker Compose

```bash
git clone https://github.com/StuMason/polar-flow-server.git
cd polar-flow-server

# Start PostgreSQL + API server
docker-compose up -d

# Check health
curl http://localhost:8000/health

# View logs
docker-compose logs -f
```

The server starts syncing data every hour automatically.

## API Usage

All endpoints are scoped by `user_id`:

```bash
# Get your Polar user ID (stored during auth)
export USER_ID=$(cat ~/.polar-flow/user_id)
export TOKEN=$(cat ~/.polar-flow/token)

# Get sleep data
curl "http://localhost:8000/api/v1/users/$USER_ID/sleep?days=30"

# Get sleep for specific date
curl "http://localhost:8000/api/v1/users/$USER_ID/sleep/2026-01-09"

# Trigger manual sync
curl -X POST \
  -H "X-Polar-Token: $TOKEN" \
  "http://localhost:8000/api/v1/users/$USER_ID/sync/trigger"
```

Visit `http://localhost:8000/docs` for interactive API documentation.

## Data Stored

**Sleep:**
- Sleep score, stages (light/deep/REM)
- HRV average and samples
- Heart rate (avg/min/max)
- Breathing rate, skin temperature

**Nightly Recharge:**
- ANS charge (autonomic nervous system)
- Sleep charge and status
- HRV, heart rate, breathing rate status

**Daily Activity:**
- Steps, distance, calories
- Active time, inactivity alerts
- Activity score

**Exercises:**
- Sport type, duration, distance
- Heart rate zones and averages
- Pace, cadence, power
- Training load

## Configuration

Environment variables (see `.env.example`):

```bash
# Database (PostgreSQL required)
DATABASE_URL=postgresql+asyncpg://polar:polar@postgres:5432/polar

# Deployment mode
DEPLOYMENT_MODE=self_hosted  # or 'saas' for Laravel integration

# Sync settings
SYNC_INTERVAL_HOURS=1
SYNC_ON_STARTUP=true
SYNC_DAYS_LOOKBACK=30

# API
API_HOST=0.0.0.0
API_PORT=8000
```

## Development

```bash
# Clone and install
git clone https://github.com/StuMason/polar-flow-server.git
cd polar-flow-server
uv sync --all-extras

# Start PostgreSQL
docker-compose up -d postgres

# Run server with hot reload
uv run polar-flow-server serve --reload

# Run tests
uv run pytest

# Type check
uv run mypy src/polar_flow_server

# Lint
uv run ruff check src/ tests/
```

## SaaS Integration (Laravel)

For managed hosting with Laravel:

1. Share PostgreSQL database between Laravel and Python service
2. Laravel manages users, billing, auth
3. Python service handles data sync and analytics
4. Laravel calls Python API for data retrieval

```php
// Laravel example
$response = Http::get("http://python-service:8000/api/v1/users/{$user->id}/sleep");
$sleepData = $response->json();
```

## Analytics (Coming Soon)

- HRV baselines (7/30/60-day rolling medians)
- Recovery score calculation
- Sleep debt tracking
- Training load analysis
- Injury risk prediction
- ML-powered insights

## Documentation

Full documentation: [stumason.github.io/polar-flow-server](https://stumason.github.io/polar-flow-server/)

- [Quick Start](https://stumason.github.io/polar-flow-server/quickstart/)
- [API Reference](https://stumason.github.io/polar-flow-server/api/overview/)
- [Architecture](https://stumason.github.io/polar-flow-server/architecture/)
- [Deployment](https://stumason.github.io/polar-flow-server/deployment/self-hosted/)

## License

MIT

## Built With

- [polar-flow](https://github.com/StuMason/polar-flow) - Modern Python SDK for Polar AccessLink API
- [Litestar](https://litestar.dev/) - Async web framework
- [SQLAlchemy](https://www.sqlalchemy.org/) - Async ORM
- [PostgreSQL](https://www.postgresql.org/) - Database
- [Polars](https://pola.rs/) - Data processing

## Managed Service

Want dashboards, mobile apps, and support without self-hosting?

Check out [stumason.dev](https://stumason.dev) - managed service built with this engine + Laravel.
