#!/bin/bash

PORT=$1
FILENAME=".env-$PORT"
QUEUE=localhost$PORT

if [ -z "$PORT" ]
  then
    echo 'Please supply the web server port as parameter.'
    exit 1
fi

brew services start redis || exit 1

echo "Reading ENV from file $FILENAME"
export $(cat $FILENAME | xargs) || (echo 'Unable to read ENV file $FILENAME' && exit 1)

echo "Celery queue $QUEUE"

# Emptify the queue, in case there are some delayed tasks we don't need anymore in development
celery --app ocpi22.tasks purge -f

# Let's restart every time a python file changes in any subdirectory
watchmedo auto-restart --directory="./" --pattern="*.py" --recursive -- celery --app ocpi22.tasks \
  worker -n celery-node-$QUEUE -Q $QUEUE -l INFO --beat

brew services stop redis
