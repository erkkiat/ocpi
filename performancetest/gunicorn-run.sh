cd .. && \
export $(cat .env-8000 | xargs) && \
clear && \
PERFORMANCE_TEST=1 gunicorn ocpiconnector.wsgi:application --bind 127.0.0.1:8000 --reload --timeout 120 --workers 17 --log-file -
