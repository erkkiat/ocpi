import logging
import os

import requests
from cachetools.func import ttl_cache
from django.conf import settings

CRITICAL = logging.CRITICAL
SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK')

USER_ACTIVITY_LOGGING_FREQUENCY_HOURS = 2


@ttl_cache(ttl=USER_ACTIVITY_LOGGING_FREQUENCY_HOURS * 60 * 60)
def log_user_activity(username: str) -> None:
    message = f'User {username} became active on {settings.HOSTNAME}.'
    logging.info(message)
    if SLACK_WEBHOOK:
        requests.post(url=SLACK_WEBHOOK, json=dict(text=message, icon_emoji=':face_with_monocle:'))


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
