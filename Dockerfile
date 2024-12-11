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

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code and set execute permissions for scripts
COPY . .
RUN chmod +x entrypoint.sh fetch_secrets.sh

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

# Copy the application code and Python environment from the build stage
COPY --from=build /app /app
COPY --from=build /usr/local /usr/local

# Expose the application port
EXPOSE 8080

# Set the entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]
