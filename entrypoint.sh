#!/bin/sh

cd /code
pip install -r requirements.txt
#sleep 10
#python manage.py makemigrations
python manage.py migrate
#python manage.py loaddata /code/data/providers.json
#echo "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser('admin', 'admin@myproject.com', 'admin')" | python manage.py shell

exec "$@"
