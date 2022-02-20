#!/bin/bash

brew services start redis
export $(cat .env | xargs)
celery purge -f
watchmedo auto-restart --directory="./" --pattern="*.py" --recursive -- celery --app ocpi22.tasks worker -l INFO --beat
brew services stop redis
