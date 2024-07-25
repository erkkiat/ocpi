#!/bin/bash

PORT=$1

if [ -z "$PORT" ]
  then
    echo 'Defaulting to port 8000. You can supply the web server port as parameter.'
    export PORT=8000
fi


export $(cat .env-$PORT | xargs)

clear && \
SEND_UPDATES=0 CPO_SIMULATOR=1 PERFORMANCE_TEST=1 uvicorn main:application --reload --workers 17 --log-level debug
