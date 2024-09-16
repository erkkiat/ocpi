FROM python:3
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH=$PYTHONPATH:/code:/code/ocpiconnector
RUN mkdir /code
COPY . /code/
COPY requirements.txt /code/
WORKDIR /code
RUN pip3 install --upgrade pip
RUN pip3 install --no-cache-dir -r requirements.txt

RUN python manage.py migrate --database=gdpr_log gdpr_assist
RUN python manage.py collectstatic --noinput

# run gunicorn
CMD gunicorn ocpiconnector.wsgi:application --bind 0.0.0.0:8080 --reload --timeout 120
