#!/bin/sh

cd /code || return
pip3 install -r requirements.txt
#sleep 10
#python manage.py makemigrations
python3 manage.py migrate
python3 manage.py migrate --database=gdpr_log gdpr_assist
#python manage.py loaddata /code/data/providers.json
python3 manage.py loaddata /code/ocpi22/data/initial.json
#echo "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser('admin', 'admin@myproject.com', 'admin')" | python manage.py shell

exec "$@"
