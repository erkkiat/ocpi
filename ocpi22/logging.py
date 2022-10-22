import logging
import os

import requests
from django.conf import settings

CRITICAL = logging.CRITICAL
SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK')


def log_error(request=None, s: str = None) -> None:
    error_message = f'{s} ({request.credentials.party() if request and hasattr(request, "credentials") else "?"} ' \
                    f'server: {settings.HOSTNAME})'
    if SLACK_WEBHOOK:
        requests.post(url=SLACK_WEBHOOK, json=dict(text=error_message))
    logging.error(error_message)


def error(s: str, request=None) -> None:
    log_error(request, s)


def info(s: str, *args, **kwargs):
    return logging.info(s, *args, **kwargs)


def warning(s: str, *args, **kwargs):
    return logging.warning(s, *args, **kwargs)


def disable(level):
    return logging.disable(level)
