#!/bin/bash
set -e  # Exit immediately if a command exits with a non-zero status

WORKER_HOSTNAME="${WORKER_NAME:-default}@%h"

# Load environment variables for local development
if [[ "$ENV" == "development" ]]; then
    ENV_FILE="$1.env" # Use entrypoint-specific .env files for development (e.g., django-server.env)
    if [[ -f "$ENV_FILE" ]]; then
        echo "Loading environment variables from $ENV_FILE..."
        export $(grep -v '^#' "$ENV_FILE" | xargs)
    else
        echo "Warning: $ENV_FILE not found. Ensure the correct environment file exists."
    fi
else
    echo "Skipping entrypoint-specific .env file loading in ENV=$ENV."
fi

# Fetch secrets only for staging and production
if [[ "$ENV" == "staging" || "$ENV" == "production" ]]; then
    if [ -x ./fetch_secrets.sh ]; then
        echo "Fetching secrets for service: $1"
        ./fetch_secrets.sh "$1"
    else
        echo "Error: fetch_secrets.sh not found or not executable."
        exit 1
    fi
fi

# Main service startup logic
case "$1" in
    django-server)
        echo "Running collectstatic..."
        python manage.py collectstatic --noinput

        # Apply migrations only in development or staging environments
        if [[ "$ENV" == "development" ]]; then
            echo "Applying database migrations for $ENV environment..."
            python manage.py migrate --noinput
        fi

        echo "Starting Django server..."
        exec gunicorn ocpiconnector.wsgi:application --bind 0.0.0.0:8000 --reload --timeout 120
        ;;
    celery-django)
        echo "Starting Celery worker for Django tasks with hostname: $WORKER_HOSTNAME and queue: $CELERY_QUEUE_NAME"
        exec celery -A ocpi22.tasks worker --loglevel=info --hostname=$WORKER_HOSTNAME -Q $CELERY_QUEUE_NAME
        ;;
    mqtt-subscriber)
        echo "Starting MQTT subscriber..."
        exec python ocpi22/cpo/mqtt/mqtt_subscriber.py
        ;;
    celery-mqtt)
        echo "Starting Celery worker for MQTT tasks with hostname: $WORKER_HOSTNAME and queue: $CELERY_QUEUE_NAME"
        exec celery -A ocpi22.cpo.mqtt.tasks worker --loglevel=info --hostname=$WORKER_HOSTNAME -Q $CELERY_QUEUE_NAME
        ;;
    *)
        echo "Unknown service: $1"
        echo "Usage: django-server | celery-django | mqtt-subscriber | celery-mqtt"
        exit 1
        ;;
esac
