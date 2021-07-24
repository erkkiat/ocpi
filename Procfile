release: ./heroku-release-commands.sh
web: gunicorn ocpiconnector.wsgi:application --bind 0.0.0.0:$PORT --reload --timeout 20
worker: celery worker --app=tasks.app
