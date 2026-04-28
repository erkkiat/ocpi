#!/bin/bash
set -e  # Exit immediately if a command exits with a non-zero status

WORKER_HOSTNAME="${WORKER_NAME:-default}@%h"

case "$1" in
    django-app)
        echo "Starting Django server..."
        exec gunicorn ocpiconnector.wsgi:application --bind 0.0.0.0:8000 --workers 4 --timeout 120 --preload
        ;;
    celery-django)
        echo "Starting Celery worker for Django tasks with hostname: $WORKER_HOSTNAME and queue: $CELERY_QUEUE_NAME"
        exec celery -A ocpi22.tasks worker --loglevel=info --hostname=$WORKER_HOSTNAME -Q $CELERY_QUEUE_NAME --beat
        ;;
    mqtt-subscriber)
        echo "Starting MQTT subscriber..."
        exec python -m ocpi22.cpo.mqtt.mqtt_subscriber
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
