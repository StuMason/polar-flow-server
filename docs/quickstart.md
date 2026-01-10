# Quick Start

Get polar-flow-server running in 5 minutes.

## Prerequisites

- Polar device (watch, fitness tracker)
- Polar AccessLink API credentials from [admin.polaraccesslink.com](https://admin.polaraccesslink.com)
- Docker (recommended) or Python 3.12+

## 1. Get Polar API Credentials

1. Go to [admin.polaraccesslink.com](https://admin.polaraccesslink.com)
2. Create a new client
3. Set redirect URI to `http://localhost:8888/callback`
4. Note your `CLIENT_ID` and `CLIENT_SECRET`

## 2. Authenticate with Polar

```bash
docker run -it --rm \
  -e CLIENT_ID=your_client_id \
  -e CLIENT_SECRET=your_client_secret \
  -v ~/.polar-flow:/root/.polar-flow \
  stumason/polar-flow-server \
  polar-flow auth
```

This opens your browser, handles OAuth, and saves the token to `~/.polar-flow/token`.

## 3. Start the Server

```bash
docker run -d \
  -p 8000:8000 \
  -v ~/.polar-flow:/root/.polar-flow \
  -v polar-data:/data \
  --name polar-flow-server \
  stumason/polar-flow-server
```

The server starts and begins syncing data every hour.

## 4. Verify

```bash
# Check health
curl http://localhost:8000/health

# Get your Polar user ID
export POLAR_USER_ID=$(cat ~/.polar-flow/user_id)

# Get sleep data
curl http://localhost:8000/api/v1/users/$POLAR_USER_ID/sleep?days=7
```

## Next Steps

- [API Reference](api/overview.md) - All available endpoints
- [Analytics](analytics.md) - How recovery scores and baselines are calculated
- [MCP Server](mcp.md) - Claude Desktop integration
- [Docker Deployment](deployment/docker.md) - Advanced Docker configuration

## From Source

```bash
git clone https://github.com/StuMason/polar-flow-server.git
cd polar-flow-server

# Install dependencies
uv sync

# Run server
uv run polar-flow-server serve
```

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/) package manager.
