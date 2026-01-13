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

# Create data directory
RUN mkdir -p /data

# Copy and set up entrypoint
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Expose port
EXPOSE 8000

# Run migrations then start server
ENTRYPOINT ["docker-entrypoint.sh"]
