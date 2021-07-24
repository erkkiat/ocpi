FROM python:3
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH=$PYTHONPATH:/code:/code/ocpiconnector:/code/ocpiconnector
RUN mkdir /code
WORKDIR /code
COPY requirements.txt /code/
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt
COPY . /code/

RUN python manage.py collectstatic --noinput

# run gunicorn
CMD gunicorn ocpiconnector.wsgi:application --bind 0.0.0.0:$PORT --reload --timeout 120
