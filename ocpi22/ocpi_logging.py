import logging
import os

import requests
from django.conf import settings

from ocpi22.messages import messages
from ocpi22.ocpi.util_party import get_sender_party
from util import DistributedCache

CRITICAL = logging.CRITICAL
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK")

USER_ACTIVITY_LOGGING_FREQUENCY_HOURS = 2


@DistributedCache(expiration=USER_ACTIVITY_LOGGING_FREQUENCY_HOURS * 60 * 60)
def log_user_activity(username: str) -> None:
    message = f"User {username} became active on {settings.HOSTNAME}."
    logging.info(message)
    if SLACK_WEBHOOK:
        requests.post(
            url=SLACK_WEBHOOK, json=dict(text=message, icon_emoji=":face_with_monocle:")
        )


@DistributedCache(expiration=USER_ACTIVITY_LOGGING_FREQUENCY_HOURS * 60 * 60)
def log_ocpi_activity(host: str) -> None:
    message = (
        f"Host {host} is sending OCPI requests to {settings.HOSTNAME} "
        f"(time window is {USER_ACTIVITY_LOGGING_FREQUENCY_HOURS}h)."
    )
    logging.info(message)
    if SLACK_WEBHOOK:
        requests.post(
            url=SLACK_WEBHOOK, json=dict(text=message, icon_emoji=":face_with_monocle:")
        )


def log_error(request=None, s: str = None, **kwargs) -> None:
    error_message = (
        f"{s} ({str(get_sender_party(request.META)) if request and getattr(request, 'META', None) else ''} "
        f"server: {settings.HOSTNAME})"
    )
    if SLACK_WEBHOOK:
        requests.post(url=SLACK_WEBHOOK, json=dict(text=error_message))
    if request:
        messages.error(request, s)
    logging.error(error_message)


def error(msg: str = None, request=None, *args, **kwargs) -> None:
    # Todo: Log to redis, since mysql atomic operations get in the way often
    return log_error(request, msg, *args, **kwargs)


def info(s: str, *args, request=None, **kwargs):
    if request:
        messages.info(request, s)
    return logging.info(s, *args, **kwargs)


def warning(s: str, *args, request=None, **kwargs):
    if request:
        messages.warning(request, s)
    return logging.warning(s, *args, **kwargs)


def disable(level):
    return logging.disable(level)
