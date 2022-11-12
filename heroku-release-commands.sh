#!/bin/sh
#python manage.py test
python3 manage.py migrate
python3 manage.py migrate --database=gdpr_log