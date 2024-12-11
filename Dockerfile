# Stage 1: Build Stage
FROM python:3.11-slim AS build

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/ocpiconnector

# Set the working directory
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    pkg-config \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x ./fetch_secrets.sh ./entrypoint.sh

# Stage 2: Final Image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/ocpiconnector
ENV PYTHONOPTIMIZE=1
ENV PATH="/usr/local/bin:$PATH"

# Set the working directory
WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the entire Python environment from the build stage
COPY --from=build /usr/local /usr/local

# Copy the application code and scripts
COPY --from=build /app/templates ./templates/
COPY --from=build /app/fetch_secrets.sh ./fetch_secrets.sh
COPY --from=build /app/entrypoint.sh ./entrypoint.sh
COPY --from=build /app/ocpiconnector ./ocpiconnector

# Expose the application port
EXPOSE 8080

# Set the entrypoint
ENTRYPOINT ["./entrypoint.sh"]
