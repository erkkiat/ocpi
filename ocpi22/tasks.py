import os
import random
from datetime import timedelta
from urllib.parse import urljoin

import celery
import cronitor.celery
import requests
import pprint
import logging

from celery import exceptions, shared_task
from celery.schedules import crontab
from django.conf import settings
from django.http import Http404
from django.utils import timezone
from django.utils.module_loading import import_string
from rest_framework import status

from ocpi22.ocpi.headers import make_headers
from ocpiconnector.ocpi_identities import Party
from ocpiconnector import slack_logging
from ocpiconnector.settings import STILL_ALIVE_FREQUENCY

pp = pprint.PrettyPrinter(indent=4).pprint
slack_logging.init()

# Set the default Django settings module for the 'celery' program.
if not 'DJANGO_SETTINGS_MODULE' in os.environ:
    os.environ['DJANGO_SETTINGS_MODULE'] = 'ocpiconnector.settings'

app = celery.Celery('ocpi22.tasks')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')
# app.conf.task_default_queue = settings.CELERY_TASK_DEFAULT_QUEUE  # This is taken care of in settings.py

app.conf.beat_schedule = {
    'run-me-every-minute': {
        'task': 'ocpi22.tasks.celery_heartbeat',
        'schedule': 60 * 60
    },
    'still-alive': {
        'task': 'ocpi22.tasks.check_still_alive',
        'schedule': STILL_ALIVE_FREQUENCY
    },
    'set-spot-prices-every-hour': {
        'task': 'ocpi22.tasks.set_spot_prices',
        'schedule': crontab(minute=0)
    },
    'update-spot-prices-daily': {
        'task': 'ocpi22.tasks.update_spot_prices',
        'schedule': crontab(minute=59)
    },
}


@app.task
def celery_heartbeat() -> bool:
    return True


@shared_task(max_retries=12, retry_backoff=300)
def update_spot_prices() -> bool:
    from ocpi22.models.dynamic_price import dynamic_price_sources
    for source in dynamic_price_sources:
        try:
            source.update()
        except Exception as e:
            logging.warning(f'Unable to fetch prices for {source.__class__}: {e}.')
    return True


@app.task
def set_spot_prices() -> bool:
    from ocpi22.models.dynamic_price import dynamic_price_sources, get_price
    for source in dynamic_price_sources:
        price = get_price(source.key, timezone.now())
        logging.info(f'Spot price at {source.key}: {price}')
        if not price:
            logging.warning(f"No price for {source.key}")
            continue
        from ocpi22.models.tariff import PriceComponent
        # noinspection PyUnresolvedReferences
        pcs = PriceComponent.objects.filter(dynamic_price_source=source.key).select_related('tariff_element__tariff')
        pcs.update(price=round(price, 3), type='ENERGY')
        for pc in pcs:
            logging.info(str(pc))
            tariff = pc.tariff_element.tariff
            logging.info(str(tariff))
            tariff.currency = source.currency
            tariff.save()
            tariff.send_updates()
            logging.info(f'Spot price {price} {source.currency} set')
        return True


# For Heroku Redis and Redis Enterprise Cloud
REDIS_URL = settings.REDIS_URL
assert settings.DEBUG or REDIS_URL, 'REDIS_URL needs to be set at least in the production'
if 'rediss' in REDIS_URL and 'ssl_cert_reqs' not in REDIS_URL:
    REDIS_URL += '?ssl_cert_reqs=CERT_NONE'

if REDIS_URL:
    app.conf.update(broker_url=REDIS_URL,
                    result_backend=REDIS_URL)

    # Load task modules from all registered Django apps.
    app.autodiscover_tasks()

    # Send pings automatically to Cronitor for Celery background tasks
    cronitor.celery.initialize(app, api_key=os.environ.get('CRONITOR_API_KEY'))
else:
    logging.error(f'{settings.HOSTNAME}: REDIS_URL not set, no connection to REDIS')


@shared_task(max_retries=0)
def command_start(data, session_uid, update_url, url):
    from ocpi22.models.session import Session
    from rest_framework.generics import get_object_or_404
    session: Session = Session.get_if_exists(uid=session_uid)
    if not session:
        logging.error(f"{settings.HOSTNAME}: Unable to find session {session_uid} to start charging.")
        return False
    try:
        # POST the start command to CPO system
        from ocpi22.cpo.util import get_callbacks_parameter
        from ocpi22.cpo.serializers import CallbacksSerializer
        result = requests.post(
            get_callbacks_parameter(CallbacksSerializer.START_TRANSACTION_URL),
            json=dict(
                location=session.location.uid,
                evse=session.evse.uid,
                session=session.uid,
                update_url=update_url
            )
        )
        result_status = 'ACCEPTED'
        result_data = result.json()
        if result_data:
            result_status = result_data.get('status')

        if result.status_code == 200:
            from ocpi22.models.location import Connector
            # session.status = 'ACTIVE'  # Don't activate yet, let's talk with the charge point first
            session.connector = get_object_or_404(Connector, uid=result_data['connector'], evse=session.evse)
            session.save()
            logging.debug('*** Response from CPO/charger to OCPI Connector worker task:')
            logging.debug(result.text)
            logging.debug(f'Activated session {session}')
            status_text = (result_status or 'ACCEPTED', 'Starting to charge', 'Lataus käynnistyy')
        else:
            logging.warning(f'Unable to start charging at {session.location}, EVSE: {session.evse.evse_id} '
                            f'status code {result.status_code} - response text: {result.text}')
            status_text = (result_status or 'FAILED', 'Unable to start charging', 'Latausta ei voida käynnistää')
    except (requests.exceptions.ConnectionError, Http404, Exception) as e:
        status_text = ('FAILED', 'Unable to start charging', 'Latausta ei voida käynnistää')
        logging.error(f'{settings.HOSTNAME}: Cannot reach {update_url}, please check your request parameters.')
        logging.error(f'{settings.HOSTNAME}: {str(e)}')

    # Send asynchronous OCPI response to eMSP
    result_data = dict(
        result=status_text[0],
        message=[
            dict(language='EN', text=status_text[1]),
            dict(language='FI', text=status_text[2])
        ]
    )
    try:
        response_url = data.get('response_url')
        requests.post(response_url, json=result_data)
    except requests.exceptions.ConnectionError as e:
        logging.error(f'{settings.HOSTNAME}: {str(e)}')


@shared_task
def send_ocpi_request(data, url: str, token_base64: str,
                      to_country_code: str, to_party_id: str,
                      from_country_code: str, from_party_id: str, method='put',
                      credentials_id=None, **_kwargs) -> dict:
    to = Party(to_country_code, to_party_id)
    sender = Party(from_country_code, from_party_id)
    try:
        logging.info(f"Sending {method.upper()} request {data.get('uid', data.get('id', ''))} to {url}")
        headers = make_headers(
            token_base64, to=to, sender=sender
        )

        kwargs = dict(url=url, json=data, headers=headers)
        if method == 'put':
            result = requests.put(**kwargs)
        elif method == 'delete':
            result = requests.delete(**kwargs)
        elif method == 'get':
            result = requests.get(**kwargs)
        elif method == 'post':
            result = requests.post(**kwargs)
        else:
            raise NotImplementedError(f'Method {method} is not supported for send_ocpi_request')

        logging.info(f"Response: {result.status_code} - {result.reason if hasattr(result, 'reason') else ''}")
        if result.status_code >= status.HTTP_400_BAD_REQUEST:
            logging.error(result.text[-500:])
            logging.error(
                f'{settings.HOSTNAME}: Unable to send update to {url}: {result.status_code} - {result.reason}')
        if credentials_id:
            from ocpi22.models.credentials import Credentials
            credentials = Credentials.get_if_exists(pk=credentials_id)
            if credentials:
                credentials.update_last_connection()
        return dict(
            status_code=result.status_code,
            json=result.json() if result.status_code < 300 else '',
            headers=dict(result.headers) if result.headers else {},
        )
    except requests.exceptions.ConnectionError:
        logging.error(f"{settings.HOSTNAME}: Unable to send an OCPI request to {str(to)} at {url}.")
        from ocpi22.models.credentials import Credentials
        if credentials_id:
            # noinspection PyUnresolvedReferences
            Credentials.objects.filter(pk=credentials_id).update(connection_status='OFFLINE')


@shared_task
def send_evse_status_update(evse_uid, endpoint_pk):
    from ocpi22.models.credentials import Endpoint
    from ocpi22.models.location import Evse
    # noinspection PyUnresolvedReferences
    evse = Evse.objects.get(uid=evse_uid)
    location = evse.location
    # noinspection PyUnresolvedReferences
    endpoint = Endpoint.objects.get(pk=endpoint_pk)
    if not endpoint.credentials.theirs:
        # Todo: No OCPI retries
        raise exceptions.Retry(
            f'Token for party {endpoint.credentials.party()} is unknown, please set Credentials.theirs',
            when=10
        )

    url = urljoin(endpoint.url, f'{location.country_code}/{location.party_id}/{location.uid}/{evse_uid}/')
    logging.info(f'Sending Evse update to {endpoint.credentials.party()} at {url}')

    # Gireve accepts only status updates, so let's make sure no other data gets through
    # They will pull full locations every 24h
    data = dict(
        status=evse.status,
        last_updated=evse.last_updated
    )
    token_base64 = endpoint.get_token_base64()
    result = requests.patch(
        url,
        data,
        headers=dict(Authorization=f'Token {token_base64}'))
    if result.status_code >= status.HTTP_400_BAD_REQUEST:
        logging.error(result.text[-400:])
        logging.error(f'{settings.HOSTNAME}: Unable to send Evse status update to '
                      f'{url}: {result.status_code} - {result.reason}')


@shared_task(max_retries=2, retry_backoff=2)
def exchange_credentials(token, url):
    from ocpiconnector.management.commands import exchange_credentials
    command = exchange_credentials.Command()
    command.handle(token_a=token, versions_endpoint_url=url)


@shared_task(max_retries=2, retry_jitter=True, retry_backoff=120)
def pull_objects(object_list, limit=20, **kwargs) -> None:
    try:
        if not object_list:
            return
        obj = object_list[0]
        url = kwargs.pop('url', None) or f"{obj.get('url')}?limit={limit}"
        response = send_ocpi_request(data=dict(), url=url, **kwargs)
        if response and response.get('status_code') < status.HTTP_400_BAD_REQUEST:
            next_url, _rel = response.get('headers').get('Link', ';').strip('<>').split(';')
            model = obj.get('model')
            viewset = import_string(obj.get('viewset'))
            for i in response.get('json', {}).get('data', []):
                try:
                    viewset.put(request=None, data=i)
                except Exception as e:
                    logging.error(f"{settings.HOSTNAME}: Unable to update {model} using data pulled from url {url} "
                                  f"for uid {i.get('uid', i.get('id', ''))}: {e}.")

            if next_url:
                kwargs['url'] = next_url
            else:
                object_list.pop(0)

            if settings.BACKGROUND_SEND:
                pull_objects.apply_async((object_list,), kwargs=kwargs, countdown=random.randint(2, 10))
            else:
                pull_objects(object_list, limit, **kwargs)
    except requests.exceptions.ConnectionError as e:
        logging.error(f"{settings.HOSTNAME}: Unable to pull objects: {e}")


@shared_task(max_retries=0)  # We will do this every 5 minutes anyways
def check_still_alive(credentials_id: int = None) -> None:
    from ocpi22.models.credentials import Credentials
    if credentials_id:
        credentials = None
        try:
            # noinspection PyUnresolvedReferences
            credentials = Credentials.objects.get(pk=credentials_id)
            requests.get(credentials.url)
            credentials.last_connection = timezone.now()
            credentials.connection_status = 'CONNECTED'
            logging.info(f"{credentials} is alive")
        except Exception as e:
            logging.error(f"{settings.HOSTNAME}: STILL ALIVE CHECK: Unable to connect to "
                          f"{credentials} ({credentials.url}): {e}")
            credentials.connection_status = 'OFFLINE'
        credentials.save(update_fields=['last_connection', 'connection_status'])
        return
    # noinspection PyUnresolvedReferences
    stale_credentials = Credentials.objects.filter(
        last_connection__lte=timezone.now() - timedelta(seconds=STILL_ALIVE_FREQUENCY),
        valid=True
    )
    logging.info(f"Checking {stale_credentials.count()} parties for alive")
    c: Credentials
    for c in stale_credentials:
        if c.is_complete():
            since_last_time = (timezone.now() - c.last_connection).seconds
            logging.info(f"{timezone.now()} - {c.last_connection}")
            logging.info(f"Checking that {c} is alive and well, last time was {int(since_last_time / 60)} min ago")
            check_still_alive.apply_async((c.pk,), countdown=random.randint(0, stale_credentials.count()))
