#!/bin/bash
set -e

# Ensure necessary directories exist
mkdir -p /app/static /app/media

WORKER_HOSTNAME="${WORKER_NAME}@%h"
QUEUE_NAME="${CELERY_QUEUE_NAME:-default}"

case "$1" in
    django-server)
        echo "Starting Django server..."
        exec gunicorn ocpiconnector.wsgi:application --bind 0.0.0.0:8080 --reload --timeout 120
        ;;
    mqtt-subscriber)
        echo "Starting MQTT subscriber..."
        exec python ocpiconnector/cpo/mqtt/mqtt_subscriber.py
        ;;
    celery-mqtt)
        echo "Starting Celery worker for MQTT tasks with hostname: $WORKER_HOSTNAME"
        exec celery -A ocpiconnector.cpo.mqtt.tasks worker --loglevel=info --hostname=$WORKER_HOSTNAME -Q $QUEUE_NAME
        ;;
    celery-django)
        echo "Starting Celery worker for Django tasks with hostname: $WORKER_HOSTNAME"
        exec celery -A ocpiconnector worker --loglevel=info --hostname=$WORKER_HOSTNAME -Q $QUEUE_NAME
        ;;
    *)
        echo "Unknown service: $1"
        echo "Usage: django-server | mqtt-subscriber | celery-mqtt | celery-django"
        exit 1
        ;;
esac
