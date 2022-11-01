import logging
import os

import requests
from cachetools.func import ttl_cache
from django.conf import settings

from ocpi22.ocpi.util_party import get_sender_party

CRITICAL = logging.CRITICAL
SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK')

USER_ACTIVITY_LOGGING_FREQUENCY_HOURS = 2


@ttl_cache(ttl=USER_ACTIVITY_LOGGING_FREQUENCY_HOURS * 60 * 60)
def log_user_activity(username: str) -> None:
    message = f'User {username} became active on {settings.HOSTNAME}.'
    logging.info(message)
    if SLACK_WEBHOOK:
        requests.post(url=SLACK_WEBHOOK, json=dict(text=message, icon_emoji=':face_with_monocle:'))


@ttl_cache(ttl=USER_ACTIVITY_LOGGING_FREQUENCY_HOURS * 60 * 60)
def log_ocpi_activity(host: str) -> None:
    message = f'Host {host} is sending OCPI requests to {settings.HOSTNAME} ' \
              f'(time window is {USER_ACTIVITY_LOGGING_FREQUENCY_HOURS}h).'
    logging.info(message)
    if SLACK_WEBHOOK:
        requests.post(url=SLACK_WEBHOOK, json=dict(text=message, icon_emoji=':face_with_monocle:'))


def log_error(request=None, s: str = None) -> None:
    error_message = f'{s} ({str(get_sender_party(request.META)) if request else ""} ' \
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
