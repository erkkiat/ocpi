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

echo "Reading ENV from file $FILENAME"
export $(cat $FILENAME | xargs) || (echo "Unable to read ENV file $FILENAME" && exit 1)

./manage.py shell
