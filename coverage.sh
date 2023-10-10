#!/usr/bin/env bash

export $(cat coverage.env | xargs) || (echo 'Unable to read ENV file' && exit 1)

coverage run --source='.' manage.py test
coverage html
