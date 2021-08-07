#!/bin/bash

export $(cat .env | xargs)
watchmedo auto-restart --directory="./" --pattern="*.py" --recursive -- celery --app ocpi22.tasks worker
