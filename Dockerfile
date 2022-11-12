FROM python:3
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH=$PYTHONPATH:/code:/code/ocpiconnector:/code/ocpiconnector
RUN mkdir /code
RUN ./manage.py migrate --database=gdpr_log
WORKDIR /code
COPY requirements.txt /code/
RUN pip3 install --upgrade pip
RUN pip3 install --no-cache-dir -r requirements.txt
COPY . /code/

RUN python manage.py collectstatic --noinput

# run gunicorn
CMD gunicorn ocpiconnector.wsgi:application --bind 0.0.0.0:$PORT --reload --timeout 120
