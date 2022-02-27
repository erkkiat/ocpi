#!/usr/bin/env bash

heroku addons:create jawsdb-maria
heroku addons:add papertrail
heroku addons:create rediscloud:30
