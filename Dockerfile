FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/ocpiconnector

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

RUN python ocpiconnector/manage.py migrate --database=gdpr_log gdpr_assist
RUN python ocpiconnector/manage.py collectstatic --noinput

EXPOSE 8080

ENTRYPOINT ["./entrypoint.sh"]
