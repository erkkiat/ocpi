import logging
import os
from datetime import datetime
from typing import Union

import pytz
import requests
from cachetools.func import ttl_cache
from django.conf import settings
from django.utils import timezone

from ocpi22.messages import messages
from ocpi22.ocpi.util_party import get_sender_party
from ocpi22.models.logging import LogEntry, LogTopic, ChildEvent, LogLevel

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


def create_log_entry(t: LogTopic) -> LogEntry:
    logentry, _created = LogEntry.objects.create(t.value)
    return logentry


def log_for_admin(text: str, logentry: Union[LogEntry, int], level=LogLevel.INFO, **kwargs) -> None:
    kwargs.pop('logentry', None)
    if isinstance(logentry, LogEntry):
        logentry = logentry.pk
    ChildEvent.objects.create(text=text, logentry_id=logentry, level=level.value, **kwargs)
    LogEntry.objects.filter(pk=logentry).update(updated=datetime.now(pytz.utc))


def get_default_logentry() -> LogEntry:
    logentry, _created = LogEntry.objects.get_or_create(topic=LogTopic.GENERIC)
    return logentry


def log_error(request=None, s: str = None, logentry=None, admin_log={}, **kwargs) -> None:
    error_message = f'{s} ({str(get_sender_party(request.META)) if request else ""} ' \
                    f'server: {settings.HOSTNAME})'
    if SLACK_WEBHOOK:
        requests.post(url=SLACK_WEBHOOK, json=dict(text=error_message))
    if request:
        messages.error(request, s)
    logentry = logentry or admin_log.pop('logentry', None) or get_default_logentry()
    log_for_admin(logentry=logentry, text=s, level=LogLevel.ERROR, **admin_log)
    logging.error(error_message)


def error(msg: str = None, request=None, *args, **kwargs) -> None:
    # Todo: Log to redis, since mysql atomic operations get in the way often
    return log_error(request, msg, *args, **kwargs)


def info(s: str, *args, request=None, logentry=None, log_to_admin=False, admin_log={}, **kwargs):
    if request:
        messages.info(request, s)
    if log_to_admin:
        logentry = logentry or admin_log.pop('logentry', None) or get_default_logentry()
        log_for_admin(logentry=logentry, text=s, level=LogLevel.INFO, **admin_log)
    return logging.info(s, *args, **kwargs)


def warning(s: str, *args, request=None, logentry=None, admin_log={}, **kwargs):
    if request:
        messages.warning(request, s)
    logentry = logentry or admin_log.pop('logentry', None) or get_default_logentry()
    log_for_admin(logentry=logentry, text=s, level=LogLevel.WARNING, **admin_log)
    return logging.warning(s, *args, **kwargs)


def disable(level):
    return logging.disable(level)
