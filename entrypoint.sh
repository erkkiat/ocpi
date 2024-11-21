#!/bin/bash
set -e

WORKER_HOSTNAME="${WORKER_NAME:-default}@%h"

# Fetch secrets
if [ -x ./fetch_secrets.sh ]; then
    echo "Fetching secrets for service: $1"
    ./fetch_secrets.sh "$1"
else
    echo "Error: fetch_secrets.sh not found or not executable."
    exit 1
fi

case "$1" in
    django-server)
        echo "Starting Django server with secrets..."
        exec gunicorn ocpiconnector.wsgi:application --bind 0.0.0.0:8080 --reload --timeout 120
        ;;
    celery-django)
        echo "Starting Celery worker for Django tasks with hostname: $WORKER_HOSTNAME and queue: $CELERY_QUEUE_NAME"
        exec celery -A ocpiconnector worker --loglevel=info --hostname=$WORKER_HOSTNAME -Q $CELERY_QUEUE_NAME
        ;;
    mqtt-subscriber)
        echo "Starting MQTT subscriber with secrets..."
        exec python ocpiconnector/cpo/mqtt/mqtt_subscriber.py
        ;;
    celery-mqtt)
        echo "Starting Celery worker for MQTT tasks with hostname: $WORKER_HOSTNAME and queue: $CELERY_QUEUE_NAME"
        exec celery -A ocpiconnector.cpo.mqtt.tasks worker --loglevel=info --hostname=$WORKER_HOSTNAME -Q $CELERY_QUEUE_NAME
        ;;
    *)
        echo "Unknown service: $1"
        echo "Usage: django-server | celery-django | mqtt-subscriber | celery-mqtt"
        exit 1
        ;;
esac