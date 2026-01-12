FROM python:3.12-slim

# Install system dependencies (curl for health checks, psycopg dependencies)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/

# Install dependencies
RUN uv sync --frozen --no-dev

# Create data directory
RUN mkdir -p /data

# Expose port
EXPOSE 8000

# Run the server
CMD ["uv", "run", "polar-flow-server", "serve"]
