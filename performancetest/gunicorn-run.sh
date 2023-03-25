#!/bin/bash

PORT=$1

if [ -z "$PORT" ]
  then
    echo 'Defaulting to port 8000. You can supply the web server port as parameter.'
    export PORT=8000
fi

cd .. && \
export $(cat .env-$PORT | xargs) && \
clear && \
PERFORMANCE_TEST=1 gunicorn ocpiconnector.wsgi:application --bind 127.0.0.1:$PORT --reload --timeout 120 --workers 17 --log-file -
