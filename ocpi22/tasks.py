import os
import celery
import requests
from icecream import ic

# Set the default Django settings module for the 'celery' program.
from rest_framework.reverse import reverse

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
def debug_task(self):
    ic(self.request)


@app.task(bind=True)
def command_start(self, data):
    from rest_framework.generics import get_object_or_404

    from ocpi22.models import Evse
    from ocpi22.sessions import create_session

    result = requests.get(
        os.environ.get('ENDPOINT_SESSION_START',
            default='http://localhost:5000' + reverse('simulate_session_start')
        )
    )
    if result.status_code == 200:
        evse = get_object_or_404(Evse, uid=data['evse_uid'])
        connector = evse.connectors.all()[0]
        # ic(evse, connector)
        _session = create_session(
            data['location_id'],
            evse.uid,
            connector.uid,
            ad_hoc_token=data['token'],
            authorize=False  # When eMSP sends a SESSION_START, they are responsible for validating their Token
        )
        print('*** Started session')
    else:
        print(f'*** Error {result.status_code} - {result.text} from charger')
