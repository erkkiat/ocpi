#!/usr/bin/env bash

USAGE='[OCPI connector instance name] [one or more OCPI roles, e.g. CPO=`FI*AAA`]'
if [ -z "$1" ]
  then
    echo $USAGE
    exit 1
fi

if [ -z "$2" ]
  then
    ROLE1="CPO='FI*CPO'"
    ROLE2="EMSP='FI*MSP'"
fi

if [ `export $(cat .env | xargs)` ]
  then
    echo 'You should have CRONITOR_API_KEY, BGDA_URL and IBEX_CREDENTIALS defined in .env'
    exit 1
fi

HEROKU_APP=$1-ocpi

echo "Creating app $HEROKU_APP..."

heroku create --region eu $HEROKU_APP \
 && heroku addons:create jawsdb-maria \
 && heroku addons:create papertrail \
 && heroku addons:create rediscloud \
 && heroku config:set CRONITOR_API_KEY=$CRONITOR_API_KEY HOSTNAME=$HEROKU_APP.herokuapp.com \
 SECRET_KEY=`python -c 'import uuid; print(uuid.uuid4())'` \
 BGDA_URL=$BGDA_URL IBEX_CREDENTIALS=$IBEX_CREDENTIALS $2 $3 $4 $ROLE1 $ROLE2 \
 && heroku pipelines:add ocpi-connector --stage=production \
 && heroku pipelines:promote --app=cpo-ocpi --to=$HEROKU_APP \
 && heroku run ./manage.py loaddata ocpi22/data/initial.json \
 && heroku run ./manage.py createsuperuser --username eki --email erkki.tapola@pohdinto.com \
 && heroku ps:scale worker=1
