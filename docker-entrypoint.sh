#!/bin/bash
set -e

# Use the baked venv binaries directly: `uv run` wants to re-verify the lock
# and (re)write .venv, which the unprivileged runtime user cannot and should
# not do.
echo "Running database migrations..."
/app/.venv/bin/alembic upgrade head

echo "Starting polar-flow-server..."
exec /app/.venv/bin/polar-flow-server serve
