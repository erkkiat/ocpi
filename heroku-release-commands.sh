#!/bin/sh

echo "running python3 manage.py migrate"
python3 manage.py migrate
echo "running python3 manage.py migrate --database=gdpr_log gdpr_assist"
python3 manage.py migrate --database=gdpr_log gdpr_assist