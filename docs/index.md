# polar-flow-server

Self-hosted health analytics server for Polar devices.

## What This Does

Polar devices collect health data: sleep, HRV, activity, exercises. The Polar API provides access to this data, but only for the last 28-30 days. This server:

1. Syncs data from Polar API automatically
2. Stores everything in a local database (DuckDB or PostgreSQL)
3. Runs analytics (HRV baselines, recovery scores, sleep debt)
4. Exposes REST API for dashboards and integrations
5. Provides MCP server for Claude Desktop integration

## Features

**Data Storage:**
- Sleep data with HRV and sleep stages
- Nightly Recharge (ANS charge, recovery metrics)
- Daily activity (steps, calories, zones)
- Exercises/workouts with detailed metrics

**Analytics:**
- Personal baselines with IQR-based anomaly detection
- Rolling averages (7-day, 30-day, 90-day)
- Automatic anomaly alerts (warning/critical severity)
- Analytics readiness tracking (feature unlock by data availability)
- Training load ratio monitoring

**Deployment:**
- Self-hosted mode: Single user, DuckDB, Docker
- SaaS mode: Multi-user, PostgreSQL, Laravel integration

## Architecture

```
Polar API → polar-flow-sdk → Sync Service → Database → Analytics → REST API
                                                                        ↓
                                                              Dashboard/App
```

Python data analytics engine:
- Litestar (async web framework)
- SQLAlchemy 2.0 (async ORM)
- DuckDB (self-hosted) or PostgreSQL (SaaS)
- Polars (data processing)
- Strict type checking with mypy

## Multi-Tenancy

Built for multi-user from day 1:
- Every database table includes `user_id` column
- All API endpoints scoped by `user_id`
- Single user for self-hosted, many users for SaaS
- Same codebase for both deployment modes

## Quick Start

### Self-Hosted (Docker)

```bash
docker run -d \
  -p 8000:8000 \
  -v ~/.polar-flow:/root/.polar-flow \
  -v polar-data:/data \
  --name polar-flow-server \
  stumason/polar-flow-server
```

### API Usage

```bash
# Get sleep data
curl http://localhost:8000/api/v1/users/12345/sleep?days=30

# Get personal baselines
curl http://localhost:8000/api/v1/users/12345/baselines

# Check if HRV is anomalous
curl http://localhost:8000/api/v1/users/12345/baselines/check/hrv_rmssd/25.5

# Check analytics feature availability
curl http://localhost:8000/api/v1/users/12345/analytics/status

# Trigger sync
curl -X POST \
  -H "X-Polar-Token: your_token" \
  http://localhost:8000/api/v1/users/12345/sync/trigger
```

## Links

- [Quick Start Guide](quickstart.md)
- [Architecture](architecture.md)
- [API Reference](api/overview.md)
- [GitHub Repository](https://github.com/StuMason/polar-flow-server)
- [polar-flow SDK](https://stumason.github.io/polar-flow/)
