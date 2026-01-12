#!/bin/bash
set -e

echo "Running database migrations..."
uv run alembic upgrade head

echo "Starting polar-flow-server..."
exec uv run polar-flow-server serve
