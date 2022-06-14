#!/usr/bin/env bash

PYTHONUNBUFFERED=1 DEBUG=1 SIMULATOR=1 REDIS_URL=redis://localhost:6379 BUSINESS_NAME=ChargerHub.EU \
HOSTNAME=testserver LOCAL_STATIC=1 JAWSDB_MARIA_URL=mysql://ocpi8000:ocpiocpi@localhost:3306/ocpi8000e \
BACKGROUND_SEND=0 CPO="FI*CPO" EMSP="FI*MSP" SECRET_KEY=iconty78qoxny73rxgnyfuskcgfagc PREMIUM=1 \
SCHEME=http coverage run --source='.' manage.py test

coverage html
