#!/bin/sh

./manage.py migrate gdpr_assist 0003 --fake
./manage.py migrate gdpr_assist 0001
./manage.py migrate gdpr_assist zero --fake
./manage.py migrate gdpr_assist
