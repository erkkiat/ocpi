# Stage 1: Build Stage
FROM python:3.11-slim AS build

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/ocpiconnector

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    pkg-config \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r /app/requirements.txt

RUN echo "Files before cleanup in build stage:" && find . -name '*.py' && \
    python -m compileall -b . && \
    echo "Compiled .pyc files:" && find . -name '*.pyc' && \
    find . -name '*.py' ! -name 'manage.py' -exec rm -f {} + && \
    echo "Files after cleanup in build stage:" && find . -name '*.py'

RUN chmod +x /app/entrypoint.sh /app/fetch_secrets.sh

# Stage 2: Final Distribution Image
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/ocpiconnector
ENV PYTHONOPTIMIZE=1
ENV PATH="/usr/local/bin:$PATH"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /app /app
COPY --from=build /usr/local /usr/local

RUN echo "Files before cleanup in final stage:" && find . -name '*.py' && \
    find . -name '*.py' ! -name 'manage.py' -exec rm -f {} + && \
    echo "Files after cleanup in final stage:" && find . -name '*.py'

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
