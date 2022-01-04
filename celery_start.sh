#!/bin/bash

brew services start redis
export $(cat .env | xargs)
watchmedo auto-restart --directory="./" --pattern="*.py" --recursive -- celery --app ocpi22.tasks worker
brew services stop redis
