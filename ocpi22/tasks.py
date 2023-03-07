import os
import random
from datetime import timedelta
from json import JSONDecodeError
from typing import Optional, Union

import celery
import cronitor.celery
import requests
import pprint

import sentry_sdk
from celery import shared_task
from celery.schedules import crontab
from django.conf import settings
from django.utils import timezone
from django.utils.module_loading import import_string
from rest_framework import status
from sentry_sdk import capture_exception

from ocpi22 import choices
from ocpi22.ocpi.headers import make_headers
from ocpiconnector.ocpi_identities import Party
from ocpiconnector.settings import STILL_ALIVE_FREQUENCY
from ocpiconnector.util import Timer

pp = pprint.PrettyPrinter(indent=4).pprint
zoined_token = os.environ.get('ZOINED_TOKEN')

# Set the default Django settings module for the 'celery' program.
if 'DJANGO_SETTINGS_MODULE' not in os.environ:
    os.environ['DJANGO_SETTINGS_MODULE'] = 'ocpiconnector.settings'

RESULT_EXPIRE_TIME = 3600  # 1 hour

app = celery.Celery('ocpi22.tasks', result_expires=RESULT_EXPIRE_TIME)

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')
# app.conf.task_default_queue = settings.CELERY_TASK_DEFAULT_QUEUE  # This is taken care of in settings.py

pull_hour = random.randint(0, 3)
pull_minute = random.randint(0, 59)

# print(f'Pulling all objects daily at {pull_hour:02d}:{pull_minute:02d}')

app.conf.beat_schedule = {
    'run-me-every-minute': {
        'task': 'ocpi22.tasks.celery_heartbeat',
        'schedule': 60 * 60
    },
    'still-alive': {
        'task': 'ocpi22.tasks.check_still_alive',
        'schedule': STILL_ALIVE_FREQUENCY
    },
    'pull-all-objects': {
        'task': 'ocpi22.tasks.pull_all_objects',
        # 'schedule': 120  # For testing
        'schedule': crontab(hour=pull_hour, minute=pull_minute)
    }
}


@app.task
def celery_heartbeat() -> bool:
    return True


@shared_task(max_retries=3, retry_backoff=3600)
def pull_all_objects() -> bool:
    from ocpi22.models.credentials import Credentials
    from ocpi22.pull import schedule_full_update

    print('Starting a scheduled full OCPI object pull.')
    credentials = Credentials.objects.filter(valid=True)
    for c in credentials:
        schedule_full_update(c)
    return True


# For Heroku Redis and Redis Enterprise Cloud
REDIS_URL = settings.REDIS_URL
assert settings.DEBUG or REDIS_URL, 'REDIS_URL or REDISCLOUD_URL needs to be set at least in the production'
if 'rediss' in REDIS_URL and 'ssl_cert_reqs' not in REDIS_URL:
    REDIS_URL += '?ssl_cert_reqs=CERT_NONE'

if REDIS_URL:
    app.conf.update(broker_url=REDIS_URL,
                    result_backend=REDIS_URL)

    # Load task modules from all registered Django apps.
    app.autodiscover_tasks()

    CRONITOR_API_KEY = os.environ.get('CRONITOR_API_KEY')
    if CRONITOR_API_KEY:
        # Send pings automatically to Cronitor for Celery background tasks
        cronitor.celery.initialize(app, api_key=CRONITOR_API_KEY)
else:
    from ocpi22 import logging
    logging.error(f'{settings.HOSTNAME}: REDIS_URL not set, no connection to REDIS')


@shared_task
def send_ocpi_request(data, url: str, token_base64: str,
                      to_country_code: str, to_party_id: str,
                      from_country_code: str, from_party_id: str, method='put',
                      credentials_id=None, title=None, **_kwargs) -> Optional[dict]:
    to = Party(to_country_code, to_party_id)
    sender = Party(from_country_code, from_party_id)
    from ocpi22 import logging

    try:
        logging.info(f"Sending {method.upper()} {title} request {data.get('uid', data.get('id', ''))} to {url}")
        headers = make_headers(
            token_base64, to=to, sender=sender
        )

        # Log the message to Sentry
        with Timer() as t:
            sentry_sdk.set_context('data', data)
        logging.info(f'Logged the message to Sentry in {float(t):.2f} seconds')

        kwargs = dict(url=url, json=data, headers=headers)

        # Call the specified method in requests, for example, if method == 'put', call requests.put
        function = getattr(requests, method)
        if not function:
            raise NotImplementedError(f'Method {method} is not supported for send_ocpi_request')

        with Timer() as t:
            result = function(**kwargs)
        logging.info(f'OCPI request response took {float(t):.2f} seconds')

        logging.info(f"Response: {result.status_code} - {result.reason if hasattr(result, 'reason') else ''}")
        if result.status_code >= status.HTTP_400_BAD_REQUEST:
            logging.error(
                f'{settings.HOSTNAME}: Unable to send update to {url}: {result.status_code} - {result.reason}')
            logging.error(result.text[-500:])
        if credentials_id:
            from ocpi22.models.credentials import Credentials
            credentials = Credentials.get_if_exists(pk=credentials_id)
            if credentials:
                credentials.update_last_connection()

        # Log the response to Sentry
        if hasattr(result, 'data') and result.data:
            # ic(result.data, result.json())
            sentry_sdk.set_context('result', result.json())

        return dict(
            status_code=result.status_code,
            json=result.json() if result.status_code < 300 else '',
            headers=dict(result.headers) if result.headers else {},
            sender=dict(country_code=to_country_code, party_id=to_party_id),
        )
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, JSONDecodeError) as e:
        logging.error(f"{settings.HOSTNAME}: Unable to send an OCPI request to {str(to)} at {url}.")
        from ocpi22.models.credentials import Credentials
        if credentials_id:
            Credentials.objects.filter(
                pk=credentials_id,
                connection_status=choices.CONNECTED).update(connection_status=choices.OFFLINE)
        capture_exception(e)
        return None


@shared_task(max_retries=2, retry_backoff=2)
def exchange_credentials(token, url):
    from ocpiconnector.management.commands import exchange_credentials
    command = exchange_credentials.Command()
    command.handle(token_a=token, versions_endpoint_url=url)


@shared_task(max_retries=2, retry_jitter=True, retry_backoff=120)
def pull_objects(object_list, limit=10, delay=2, logentry_id=None, total_objects=0, **kwargs) -> None:
    from ocpi22 import logging

    try:
        if not object_list:
            logging.info('Empty object list, nothing to pull')
            return
        next_url = ''
        obj = object_list[0]
        url = kwargs.pop('url', obj.get('url', ''))
        if url:
            if "limit=" not in url:
                url = f"{url}?limit={limit}"
            response = send_ocpi_request(data=dict(), url=url, **kwargs)
            if response and response.get('status_code') < status.HTTP_400_BAD_REQUEST:
                next_url, _rel = response.get('headers').get('Link', ';').strip('<>').split(';')
                model = obj.get('model')
                viewset = import_string(obj.get('viewset'))
                items = response.get('json', {}).get('data', [])
                total_objects += len(items)
                for i in items:
                    try:
                        # TODO: Check that party matches with Credentials, don't allow third party data
                        response = viewset().put(request=None, data=i, logentry=logentry_id)
                        if response.status_code >= status.HTTP_400_BAD_REQUEST:
                            raise Exception(response.data.get('status_message', '<no status message provided>'))
                    except Exception as e:
                        logging.error(f"Unable to update {model} using data pulled from url {url} "
                                      f"for uid {i.get('uid', i.get('id', ''))}: {e}.", logentry=logentry_id)
                if next_url:
                    kwargs['url'] = next_url
        else:
            module_name = obj.get('model').split('.')[-1]
            logging.warning(f'Party {obj.get("party")} is not a {module_name} sender, skipping', logentry=logentry_id)

        if not next_url:
            object_list.pop(0)
            if not len(object_list):
                logging.info(f'Total of {total_objects} objects pulled', logentry=logentry_id, log_to_admin=True)
                return

        countdown = random.randint(delay, int(1.5 * delay))

        if settings.BACKGROUND_SEND:
            # logging.info(f'Scheduling the next pull for {kwargs.get("url")} in {countdown} seconds')
            # logging.info(f'My default_queue: {app.conf.task_default_queue}')

            # pull_objects.subtask((object_list, limit), kwargs=kwargs, countdown=countdown)
            pull_objects.apply_async((object_list, limit, delay, logentry_id, total_objects),
                                     kwargs=kwargs, countdown=countdown)
        else:
            pull_objects(object_list, limit, delay, logentry_id, total_objects, **kwargs)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        logging.error(f"Unable to pull objects: {e}", logentry=logentry_id)


@shared_task(max_retries=0)  # We will do this every 5 minutes anyways
def check_still_alive(credentials_id: int = None) -> None:
    from ocpi22.models.credentials import Credentials
    from ocpi22 import logging

    if credentials_id:
        credentials = None
        time_since_last_connection = None
        try:
            credentials: Credentials = Credentials.objects.get(pk=credentials_id)
            time_since_last_connection = (timezone.now() - credentials.last_connection).total_seconds()
            requests.get(credentials.url, timeout=20)
            credentials.last_connection = timezone.now()
            credentials.connection_status = choices.CONNECTED
            logging.info(f"{credentials} is alive")
        except requests.exceptions.ConnectionError:
            logging.error(f"{settings.HOSTNAME}: {credentials} is *NOT* alive ({credentials.url}), "
                          f"last connection was {int(time_since_last_connection / 60)} minutes ago")
            credentials.connection_status = choices.OFFLINE
        except Exception as e:
            logging.error(f"{settings.HOSTNAME}: STILL ALIVE CHECK: Unable to connect to "
                          f"{credentials} ({credentials.url}): {type(e)} - {e}")
            credentials.connection_status = choices.OFFLINE
        credentials.save(update_fields=['last_connection', 'connection_status'])
        return
    stale_credentials = Credentials.objects.filter(
        last_connection__lte=timezone.now() - timedelta(seconds=STILL_ALIVE_FREQUENCY - 3),
        valid=True
    )
    # logging.info(f"Checking {stale_credentials.count()} parties for alive")
    c: Credentials
    for c in stale_credentials:
        if c.is_complete() and c.connection_status in (choices.CONNECTED, choices.OFFLINE):
            # since_last_time = (timezone.now() - c.last_connection).seconds
            # logging.info(f"Checking that {c} is alive and well, last successful "
            #              f"connection was {int(since_last_time / 60)} min ago")
            check_still_alive.apply_async((c.pk,), countdown=random.randint(0, stale_credentials.count()))


@app.task(max_retries=5, default_retry_delay=120)
def send_data_to_analytics(data: Union[dict, list], url):
    from ocpi22 import logging
    if not zoined_token:
        # logging.info(f'No Zoined token set => no update to analytics')
        return
    headers = {'content-type': 'application/json', 'Authorization': f'Bearer {zoined_token}'}
    # Todo: Async send
    if isinstance(data, dict):
        data = [data]
    response = requests.post(url=url, json=data, headers=headers, timeout=5)
    if response.status_code != 200:
        logging.error(f'Unable to send update to analytics: {response.text}')
    # else:
    #     logging.info(f'Update sent to analytics: {response.text}')
