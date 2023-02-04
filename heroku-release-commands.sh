#!/bin/sh
#python manage.py test
cd /code

if [ ! -f "manage.py" ]; then
    echo "Looks like the Django app has not been loaded to this instance."
    exit 99
fi

python3 manage.py migrate
python3 manage.py migrate --database=gdpr_log gdpr_assist