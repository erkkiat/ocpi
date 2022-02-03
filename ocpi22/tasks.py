import json
import os
from urllib.parse import urljoin

import celery
import cronitor.celery
import requests
import pprint
import logging

from celery import exceptions
from celery.schedules import crontab
from django.http import Http404
from rest_framework import status

from ocpiconnector import slack_logging, nordpool

pp = pprint.PrettyPrinter(indent=4).pprint
slack_logging.init()

# Set the default Django settings module for the 'celery' program.
os.environ['DJANGO_SETTINGS_MODULE'] = 'ocpiconnector.settings'

app = celery.Celery('ocpi22.tasks')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')
app.conf.beat_schedule = {
    'run-me-every-minute': {
        'task': 'ocpi22.tasks.celery_heartbeat',
        'schedule': 60
    },
    'set-spot-price-every-hour': {
        'task': 'ocpi22.tasks.set_spot_price',
        'schedule': crontab(minute=0),
    },
}


@app.task
def celery_heartbeat() -> bool:
    return True


@app.task
def set_spot_price() -> bool:
    # This will just trigger a ping to Cronitor, but you can use it for once-per-minute tasks also
    from ocpi22.models.tariff import Tariff
    tariff = Tariff.get_if_exists(uid='TNORDPOOL')
    if tariff:
        electricity_spot_price = nordpool.get_current_price('FI')
        # Find the first energy based price_component Set the spot price
        for te in tariff.tariff_elements.all():
            for pc in te.price_components.all():
                if pc.type == 'ENERGY':
                    pc.price = electricity_spot_price
                    pc.save()
                    logging.error(f'Spot price {electricity_spot_price}€ set')
                    return True
    logging.error('Cannot set spot price')
    raise celery.exceptions.CeleryWarning('Cannot set spot price')


REDIS_URL = os.environ['REDIS_URL']
if 'rediss' in REDIS_URL and 'ssl_cert_reqs' not in REDIS_URL:
    REDIS_URL += '?ssl_cert_reqs=CERT_NONE'

app.conf.update(broker_url=REDIS_URL,
                result_backend=REDIS_URL)

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Send pings automatically to Cronitor for Celery background tasks
cronitor.celery.initialize(app, api_key=os.environ.get('CRONITOR_API_KEY'))


@app.task(bind=True)
def command_start(_self, data, session_uid, update_url, url):
    from ocpi22.models.session import Session
    from rest_framework.generics import get_object_or_404
    session: Session = get_object_or_404(Session, uid=session_uid)

    try:
        # POST the start command to CPO system
        result = requests.post(
            os.environ.get('ENDPOINT_SESSION_START', default=url),  # For testing, append: + '?force_result=EVSE_OCCUPIED',
            data=dict(
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
        logging.error(f'Cannot reach {update_url}, please check your request parameters.')
        logging.error(str(e))

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
        requests.post(response_url, data=json.dumps(result_data).encode('utf8'))
    except requests.exceptions.ConnectionError as e:
        logging.error(str(e))


@app.task(bind=True)
def send_update(_self, data, url, token_base64) -> None:
    logging.info(f'Sending update to {url}')

    result = requests.put(
        url,
        json=data,
        headers=dict(Authorization=f'Token {token_base64}'))
    logging.info(f"Response: {result.status_code} - {result.reason}")
    if result.status_code >= status.HTTP_400_BAD_REQUEST:
        logging.error(result.text[-500:])
        logging.error(f'Unable to send update to {url}: {result.status_code} - {result.reason}')


@app.task(bind=True)
def send_evse_status_update(_self, evse_uid, endpoint_pk):
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
    logging.error(f'Sending Evse update to {endpoint.credentials.party()} at {url}')

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
        logging.error(f'Unable to send Evse status update to {url}: {result.status_code} - {result.reason}')
