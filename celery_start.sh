#!/bin/bash

PORT=$1

if [ -z "$PORT" ]
  then
    echo 'Defaulting to port 8000. You can supply the web server port as parameter.'
    export PORT=8000
fi

FILENAME=".env-$PORT"
QUEUE=localhost$PORT

source venv/bin/activate || exit 1
pip install -r requirements.txt || exit 1

echo "Reading ENV from file $FILENAME"
export $(grep -v '^#' $FILENAME | xargs) || (echo "Unable to read ENV file $FILENAME" && exit 1)
echo "Celery queue $QUEUE"
export CELERY_QUEUE=$QUEUE

# Emptify the queue, in case there are some delayed tasks we don't need anymore in development
celery --app ocpi22.tasks purge -f || exit 1

# Let's restart every time a python file changes in any subdirectory
watchmedo auto-restart --directory="./" --pattern="*.py" --recursive -- celery --app ocpi22.tasks \
  worker -n celery-node-$QUEUE -Q $QUEUE -l INFO --beat || exit 1
