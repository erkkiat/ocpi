# ---- Stage 1: Build Dependencies ----
FROM python:3.11-slim AS build

# Base environment configuration
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/ocpiconnector

# uv best practice flags
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Install build-time system dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential python3-dev libpq-dev pkg-config default-libmysqlclient-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# ✅ Install uv using pinned official binary (verify in CI with GitHub attestation)
COPY --from=ghcr.io/astral-sh/uv:0.7.2 /uv /uvx /bin/

# Copy lock and manifest files first for caching
COPY pyproject.toml uv.lock /app/

# Create a virtualenv
RUN uv venv .venv

# Add venv to path
ENV PATH="/app/.venv/bin:$PATH"

# ✅ Sync only dependencies, not project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project

# Copy actual application code
COPY . /app

# ✅ Sync project (non-editable mode)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

# Optional: Precompile to bytecode
RUN python -m compileall -b . && \
    find . -name '*.py' ! -name 'manage.py' -delete

# Ensure scripts are executable
RUN chmod +x /app/entrypoint.sh /app/fetch_secrets.sh

# ---- Stage 2: Final Runtime Image ----
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/ocpiconnector
ENV PYTHONOPTIMIZE=1
ENV PATH="/usr/local/bin:/app/.venv/bin:$PATH"

WORKDIR /app

# Install runtime-only system dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    libpq5 default-libmysqlclient-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy code and environment from build
COPY --from=build /app /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=build /usr/local/bin /usr/local/bin

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
