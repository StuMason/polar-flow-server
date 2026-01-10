# polar-flow-server

Self-hosted health analytics server for Polar devices. Own your data, analyze it yourself.

## What This Does

Polar devices (watches, fitness trackers) collect health data: sleep, HRV, activity, exercises. The Polar API gives you access to this data, but only for the last 28-30 days. No long-term trends, no baselines, no recovery analysis.

This server fixes that. It:

1. **Syncs** your data from the Polar API automatically
2. **Stores** everything in a local database (your data, your disk)
3. **Analyzes** the data (HRV baselines, recovery scores, sleep debt, training load)
4. **Exposes** a REST API so you can build dashboards, apps, or integrations

Think of it as your personal health data warehouse with built-in analytics.

## Why Self-Host

- **Own your data** - Not locked into Polar's 28-day window
- **Deep analysis** - HRV baselines over months/years, not days
- **Privacy** - Your health data stays on your server
- **Extensible** - Build your own dashboards, connect to other tools
- **Free** - No subscription, no limits

## Architecture

```
Polar API → polar-flow SDK → Scheduler → Database → Analytics Engine → REST API
                                                                            ↓
                                                              Your Dashboard/App
```

**Components:**

- **Scheduler** - Fetches new data every hour using [polar-flow](https://github.com/StuMason/polar-flow)
- **Database** - DuckDB (embedded) or TimescaleDB (production)
- **Analytics** - HRV baselines, recovery scores, sleep debt calculations
- **API** - FastAPI endpoints for querying your data
- **MCP Server** (optional) - Claude Desktop integration for AI health insights

## What You Get

**Data Storage:**
- Sleep data (scores, stages, HRV, breathing rate)
- Nightly Recharge (ANS charge, recovery metrics)
- Activities (steps, calories, distance, zones)
- Exercises (workouts with heart rate, pace, samples)

**Computed Metrics:**
- HRV baselines (7-day, 30-day rolling averages)
- HRV deviation from baseline (%)
- Recovery status (recovered, recovering, strained)
- Sleep debt tracking
- Training load and readiness scores

**API Endpoints:**
- `/recovery/today` - Current recovery status
- `/sleep/history` - Historical sleep data with computed metrics
- `/activity/list` - Activity summaries
- `/hrv/trends` - HRV trends and baselines
- `/sync/trigger` - Manual sync endpoint

## Prerequisites

- A Polar device (watch, fitness tracker)
- Polar AccessLink API credentials ([get them here](https://admin.polaraccesslink.com))
- Docker (easiest) or Python 3.11+
- 100MB disk space (grows with your data)

## Quick Start

### 1. Get Polar API Credentials

1. Go to [admin.polaraccesslink.com](https://admin.polaraccesslink.com)
2. Create a new client
3. Set redirect URI to `http://localhost:8888/callback`
4. Note your `CLIENT_ID` and `CLIENT_SECRET`

### 2. Authenticate

```bash
docker run -it --rm \
  -e CLIENT_ID=your_client_id \
  -e CLIENT_SECRET=your_client_secret \
  -v ~/.polar-flow:/root/.polar-flow \
  stumason/polar-flow-server \
  polar-flow auth
```

This opens your browser, handles OAuth, and saves the token.

### 3. Run the Server

```bash
docker run -d \
  -p 8000:8000 \
  -v ~/.polar-flow:/root/.polar-flow \
  -v polar-data:/data \
  --name polar-flow-server \
  stumason/polar-flow-server
```

That's it. The server starts syncing your data every hour.

### 4. Check Your Data

```bash
curl http://localhost:8000/recovery/today
```

## Installation

### Docker (Recommended)

See Quick Start above.

### Docker Compose

```yaml
version: "3.8"

services:
  polar-flow-server:
    image: stumason/polar-flow-server:latest
    ports:
      - "8000:8000"
    volumes:
      - ~/.polar-flow:/root/.polar-flow
      - polar-data:/data
    environment:
      - SYNC_INTERVAL_HOURS=1
    restart: unless-stopped

volumes:
  polar-data:
```

### From Source

```bash
git clone https://github.com/StuMason/polar-flow-server.git
cd polar-flow-server

# Install dependencies
uv sync

# Authenticate
uv run polar-flow auth

# Run server
uv run python -m polar_flow_server
```

## Configuration

Environment variables:

- `DATABASE_PATH` - Path to DuckDB file (default: `/data/polar.db`)
- `SYNC_INTERVAL_HOURS` - How often to sync (default: `1`)
- `SYNC_ON_STARTUP` - Sync immediately on start (default: `true`)
- `API_HOST` - API host (default: `0.0.0.0`)
- `API_PORT` - API port (default: `8000`)

## API Documentation

Once running, visit `http://localhost:8000/docs` for interactive API documentation.

Key endpoints:

**Recovery:**
- `GET /recovery/today` - Current recovery status with score and recommendation
- `GET /recovery/history?days=7` - Recovery history

**Sleep:**
- `GET /sleep/history?days=30` - Sleep data with computed metrics
- `GET /sleep/debt` - Current sleep debt

**Activity:**
- `GET /activity/list` - Recent activities
- `GET /activity/trends` - Activity trends

**HRV:**
- `GET /hrv/trends?days=90` - HRV baselines and trends

**Sync:**
- `POST /sync/trigger` - Manually trigger data sync
- `GET /sync/status` - Check sync status

## Analytics Explained

### HRV Baseline

Calculates rolling median HRV over 7 and 30 days. Median is used instead of mean to reduce impact of outliers (bad sleep, alcohol, etc.).

**Why it matters:** HRV below your baseline indicates stress, fatigue, or illness. HRV above baseline indicates good recovery.

### Recovery Score

Weighted combination of:
- HRV deviation (40%)
- Sleep score (30%)
- ANS charge (20%)
- Sleep duration (10%)

**Scale:** 0-100
- 70+ = Recovered (ready for intense training)
- 50-70 = Recovering (moderate training ok)
- <50 = Strained (prioritize rest)

### Sleep Debt

Cumulative sleep deficit relative to your target (default 8 hours). Includes decay factor - old debt gradually diminishes.

**Why it matters:** Sleep debt accumulates and impacts recovery, performance, and health.

## MCP Server (Claude Integration)

Optional feature for Claude Desktop users. Enables natural language queries:

- "What's my recovery status?"
- "Should I train hard today?"
- "Show my HRV trends this month"
- "Am I getting enough sleep?"

Enable by setting `ENABLE_MCP=true`.

## Development

```bash
# Run tests
uv run pytest

# Run with hot reload
uv run uvicorn polar_flow_server.main:app --reload

# Run sync manually
uv run python -m polar_flow_server.sync
```

## Contributing

Contributions welcome! This is a personal project but PRs for bug fixes, new analytics, or features are appreciated.

## License

MIT

## Acknowledgments

Built on [polar-flow](https://github.com/StuMason/polar-flow), a modern Python SDK for the Polar AccessLink API.

## Support

This is a self-hosted tool. No support provided, but feel free to open issues for bugs or feature requests.

If you want a managed version with dashboards, mobile apps, and support, check out [stumason.dev](https://stumason.dev).
