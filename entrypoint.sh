#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Check the first argument passed to the container
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
        echo "Starting Celery worker for MQTT tasks..."
        exec celery -A ocpiconnector.cpo.mqtt.tasks worker --loglevel=info
        ;;
    celery-django)
        echo "Starting Celery worker for Django tasks..."
        exec celery -A ocpiconnector worker --loglevel=info
        ;;
    *)
        echo "Unknown service: $1"
        echo "Usage: django-server | mqtt-subscriber | celery-mqtt | celery-django"
        exit 1
        ;;
esac
