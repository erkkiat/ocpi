# Stage 1: Build Stage
FROM python:3.9-slim AS build

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/ocpiconnector

# Set the working directory
WORKDIR /app

# Install system dependencies
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

# Copy the Django application code
COPY . .

# Precompile Python files
RUN python -m compileall .

# Ensure the scripts are executable
RUN chmod +x ./fetch_secrets.sh ./entrypoint.sh

# Stage 2: Final Image
FROM python:3.9-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/ocpiconnector
ENV PYTHONOPTIMIZE=1

# Set the working directory
WORKDIR /app

# Install runtime-only system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy compiled Python files and necessary runtime files from the build stage
COPY --from=build /app/__pycache__/ ./__pycache__/
COPY --from=build /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages
COPY --from=build /app/static ./static/
COPY --from=build /app/templates ./templates/
COPY --from=build /app/fetch_secrets.sh ./fetch_secrets.sh
COPY --from=build /app/entrypoint.sh ./entrypoint.sh

# Expose the application port
EXPOSE 8080

# Set the entrypoint
ENTRYPOINT ["./entrypoint.sh"]
