#!/usr/bin/env bash

export $(cat .env | xargs)
export REDIS_URL='redis://localhost:6379'

PORT=$1
USERNAME="ocpi$PORT"
echo Create password:
read -r PASSWORD

echo "CREATE DATABASE IF NOT EXISTS $USERNAME;" | mysql
echo "CREATE USER IF NOT EXISTS '$USERNAME'@'localhost' IDENTIFIED BY '$PASSWORD';" | mysql
echo "GRANT ALL PRIVILEGES ON * . * TO '$USERNAME'@'localhost';" | mysql

export HOSTNAME="localhost:$PORT"
export JAWSDB_MARIA_URL="mysql://ocpi$PORT:$PASSWORD@localhost:3306/ocpi$PORT"
./manage.py migrate
./manage.py loaddata ocpi22/data/initial.json
./manage.py createsuperuser --username eki --email erkki.tapola@solidroam.com
