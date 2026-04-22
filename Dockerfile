# ---- Stage 1: Build Dependencies ----
FROM python:3.11-slim AS build

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/ocpiconnector

WORKDIR /app

# Install required system dependencies with improved caching
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential python3-dev libpq-dev pkg-config default-libmysqlclient-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements to leverage Docker caching
COPY requirements.txt /app/

# Install pip tools, wheel, and setuptools FIRST to fix wheel-building errors
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Now copy the rest of the app (this prevents unnecessary invalidation of cache)
COPY . /app

# Collect static files once at build time — baked into the image.
# WhiteNoise serves them at runtime; no collectstatic needed on pod startup.
RUN DJANGO_SETTINGS_MODULE=ocpiconnector.settings.collectstatic \
    python manage.py collectstatic --noinput

# Compile Python files and remove unneeded sources
RUN python -m compileall -b . && \
    find . -name '*.py' ! -name 'manage.py' -delete

RUN chmod +x /app/entrypoint.sh /app/fetch_secrets.sh

# ---- Stage 2: Final Image ----
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/ocpiconnector
ENV PYTHONOPTIMIZE=1
ENV PATH="/usr/local/bin:$PATH"

WORKDIR /app

# Install only necessary runtime dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    libpq5 default-libmysqlclient-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy compiled application from build stage
COPY --from=build /app /app
COPY --from=build /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=build /usr/local/bin /usr/local/bin

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
