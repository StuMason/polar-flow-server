FROM python:3.12-slim

# Install system dependencies (curl/wget for health checks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src/ src/
COPY alembic/ alembic/

# Install dependencies
RUN uv sync --frozen --no-dev

# Persistent data directory. KEY_DIR moves the auto-generated encryption/session
# keys off the (ephemeral) container home dir — mount a volume over /data or the
# keys are regenerated on every recreate and stored Polar tokens become unreadable.
RUN mkdir -p /data/keys
ENV KEY_DIR=/data/keys

# Copy and set up entrypoint
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Expose port
EXPOSE 8000

# Run migrations then start server
ENTRYPOINT ["docker-entrypoint.sh"]
