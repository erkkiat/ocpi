import json
import os
import celery
import requests

import pprint
pp = pprint.PrettyPrinter(indent=4).pprint

import logging
from slack_logger import SlackHandler, SlackFormatter

sh = SlackHandler(os.environ.get('SLACK_WEBHOOK'))
sh.setFormatter(SlackFormatter())
sh.setLevel(logging.DEBUG)
logging.basicConfig(handlers=[sh])

# Set the default Django settings module for the 'celery' program.
os.environ['DJANGO_SETTINGS_MODULE'] = 'ocpiconnector.settings'

app = celery.Celery('ocpi22.tasks')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

app.conf.update(broker_url=os.environ.get('REDIS_URL'),
                result_backend=os.environ.get('REDIS_URL'))

# Load task modules from all registered Django apps.
app.autodiscover_tasks()


@app.task(bind=True)
def command_start(_self, data, session_uid, update_url, url):
    from ocpi22.models import Session
    from rest_framework.generics import get_object_or_404
    session: Session = get_object_or_404(Session, uid=session_uid)

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
        from ocpi22.models import Connector
        session.status = 'ACTIVE'
        session.connector = get_object_or_404(Connector, uid=result_data['connector'], evse=session.evse)
        session.save()
        logging.debug('*** Response from CPO/charger to OCPI Connector worker task:')
        logging.debug(result.text)
        logging.debug(f'Activated session {session}')
        status = (result_status or 'ACCEPTED', 'Starting to charge', 'Lataus käynnistyy')
    else:
        logging.warning(f'Unable to start charging at {session.location}, EVSE: {session.evse.evse_id} '
                     f'status code {result.status_code} - response text: {result.text}')
        status = (result_status or 'FAILED', 'Unable to start charging', 'Latausta ei voida käynnistää')

    # Send asynchronous OCPI response to eMSP
    result_data = dict(
        result=status[0],
        message=[
            dict(language='EN', text=status[1]),
            dict(language='FI', text=status[2])
        ]
    )
    response_url = data.get('response_url')
    requests.post(response_url, data=json.dumps(result_data).encode('utf8'))
