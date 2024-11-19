# Stage 1: Build Stage
FROM python:3.9-slim AS build

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/ocpiconnector

# Set the working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
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

# Stage 2: Final Image
FROM python:3.9-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/ocpiconnector
ENV PYTHONOPTIMIZE=1  # Enable Python optimization (-O)

# Set the working directory
WORKDIR /app

# Install runtime-only system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only compiled files from the build stage
COPY --from=build /app/__pycache__/ ./__pycache__/
COPY --from=build /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages

# Copy non-Python files required for runtime
COPY --from=build /app/static ./static/
COPY --from=build /app/templates ./templates/
COPY --from=build /app/entrypoint.sh ./entrypoint.sh

# Ensure the entrypoint script is executable
RUN chmod +x ./entrypoint.sh

# Expose the application port
EXPOSE 8080

# Set the entrypoint
ENTRYPOINT ["./entrypoint.sh"]
