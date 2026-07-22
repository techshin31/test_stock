# Dockerfile for Python Backend API & PAPER Trader
FROM python:3.10-slim-bullseye

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt-get/lists/*

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONPATH=/app

# Copy dependency manifests
COPY pyproject.toml uv.lock README.md /app/

# Synchronize dependencies
RUN uv sync --frozen --no-install-project

# Copy application source code
COPY core /app/core
COPY api /app/api
COPY apps /app/apps
COPY storage /app/storage
COPY reports /app/reports
COPY docs /app/docs
COPY scheduler.py run_live_trader.py /app/

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
