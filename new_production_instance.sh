#!/usr/bin/env bash

clear

USAGE='[instance name] [username] [email] [one or more OCPI roles, e.g. CPO=`FI*AAA`]'
if [ -z "$3" ]
  then
    echo "$USAGE"
    exit 1
fi

if [ -z "$4" ]
  then
    ROLE1="CPO=FI*CPO"
    ROLE2="EMSP=FI*MSP"
fi

export $(cat .env | xargs)

HOST=$1
USERNAME=$2
EMAIL=$3
export HEROKU_APP=$1-ocpi
PASSWORD=$(python generate_password.py)

 echo "======================================================" \
 && echo "URL: http://$HOST.ocpiconnector.com/" \
 && echo "User: $USERNAME" \
 && echo "Password: $PASSWORD" \
 && echo "======================================================"

sleep 4

echo "Creating app $HEROKU_APP..."

(heroku create --region eu "$HEROKU_APP" \
 && heroku addons:create rediscloud:100 \
 && heroku addons:create heroku-postgresql:essential-0 \
 && sleep 60 \
 && heroku config:set HOSTNAME="$HOST".ocpiconnector.com \
 SECRET_KEY=`python -c 'import uuid; print(uuid.uuid4())'` "$4" "$5" "$6" "$ROLE1" "$ROLE2" \
 SLACK_WEBHOOK="$SLACK_WEBHOOK" DJANGO_SETTINGS_MODULE="$DJANGO_SETTINGS_MODULE" SCHEME=http \
 && echo "Let's give the Redis installer a moment to settle down..." \
 && sleep 15 \
 && heroku pipelines:add ocpi-connector --stage=production \
 && heroku pipelines:promote --app=cpo-ocpi --to="$HEROKU_APP" \
 && heroku run ./manage.py createsuperuser --username eki --email erkki.tapola@pohdinto.com \
 && echo "======================================================" \
 && echo "URL: http://$HOST.ocpiconnector.com/" \
 && echo "User: $USERNAME" \
 && echo "Password: $PASSWORD" \
 && echo "======================================================" \
 && heroku run  DJANGO_SUPERUSER_USERNAME="$USERNAME" \
                DJANGO_SUPERUSER_PASSWORD="$PASSWORD" \
                ./manage.py createsuperuser --username "$USERNAME" --email "$EMAIL" --noinput) || (echo "Instance creation failed" && exit 1)

heroku addons:create papertrail || echo "*** Cannot activate papertrail"
heroku addons:create sentry || echo "*** Cannot activate sentry"
heroku addons:create moesif:free || echo "*** Cannot activate moesif API analytics"

# Too many connections for the free database
heroku ps:scale worker=1

echo "Please go to https://www.hover.com/control_panel/domain/ocpiconnector.com/dns to configure the DNS."
