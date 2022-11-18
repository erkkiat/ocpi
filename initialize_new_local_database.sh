#!/usr/bin/env bash

PORT=$1
USERNAME="ocpi$PORT"
echo Create password:
read -r PASSWORD

echo "CREATE DATABASE IF NOT EXISTS $USERNAME;" | mysql
echo "CREATE USER IF NOT EXISTS '$USERNAME'@'localhost' IDENTIFIED BY '$PASSWORD';" | mysql
echo "GRANT ALL PRIVILEGES ON * . * TO '$USERNAME'@'localhost';" | mysql

export REDIS_URL=''
export HOSTNAME="localhost:$PORT"
export JAWSDB_MARIA_URL="mysql://ocpi$PORT:$PASSWORD@localhost:3306/ocpi$PORT"
./manage.py migrate
./manage.py loaddata ocpi22/data/initial.json
./manage.py createsuperuser --username eki --email erkki.tapola@pohdinto.com
