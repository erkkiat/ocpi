#!/bin/bash

export REDIS_URL=redis://:pf0c3f4016defc774da66f3e6ff5309b085d0d2bd287fd082cd7175d87f08e027@ec2-63-34-222-58.eu-west-1.compute.amazonaws.com:23719 DEBUG=1 SLACK_WEBHOOK=https://hooks.slack.com/services/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
watchmedo auto-restart --directory="./" --pattern="*.py" --recursive -- celery --app ocpi22.tasks worker
