import json
import os
import celery
import requests

import pprint
pp = pprint.PrettyPrinter(indent=4).pprint

# Set the default Django settings module for the 'celery' program.
os.environ['DJANGO_SETTINGS_MODULE'] = 'ocpiconnector.settings'

app = celery.Celery('ocpi22.tasks')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

app.conf.update(broker_url=os.environ['REDIS_URL'],
                result_backend=os.environ['REDIS_URL'])

# Load task modules from all registered Django apps.
app.autodiscover_tasks()


@app.task(bind=True)
def command_start(_self, data, url=''):
    from rest_framework.generics import get_object_or_404
    from ocpi22.models import Evse
    from ocpi22.sessions import create_session

    # POST the start command to CPO system
    result = requests.post(
        os.environ.get('ENDPOINT_SESSION_START', default=url),  # For testing, append: + '?force_result=EVSE_OCCUPIED',
        data=dict(
            location=data['location_id'],
            evse=data['evse_uid']
        )
    )
    result_status = 'ACCEPTED'
    result_data = result.json()
    if result_data:
        result_status = result_data.get('status')

    if result.status_code == 200:
        # If CPO responds ok, create the new Session
        evse = get_object_or_404(Evse, uid=data['evse_uid'])
        connector = evse.connectors.all()[0]
        session = create_session(
            data['location_id'],
            evse.uid,
            connector.uid,
            ad_hoc_token=data['token'],
            authorize=False  # When eMSP sends a SESSION_START, they are responsible for validating their Token
        )
        print(f'*** Started session {session} - {result.text}')
        status = (result_status or 'ACCEPTED', 'Starting to charge', 'Lataus käynnistyy')
    else:
        print(f'*** Error {result.status_code} - {result.text} from charger')
        status = (result_status or 'FAILED', 'Unable to start charging', 'Latausta ei voida käynnistää')

    # Respond to eMSP
    result_data = dict(
        result=status[0],
        message=[
            dict(language='EN', text=status[1]),
            dict(language='FI', text=status[2])
        ]
    )
    response_url = data.get('response_url')
    requests.post(response_url, data=json.dumps(result_data).encode('utf8'))
