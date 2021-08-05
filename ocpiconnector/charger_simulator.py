import json
import logging

from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from pprint import PrettyPrinter

from ocpi22.models import Evse

pp = PrettyPrinter(indent=4).pprint


@csrf_exempt
def session_start(request):
    """
    Simulate CPO/charger interface, where the session start commands end up
    """

    status = 200
    result = dict(
        mode='SIMULATOR',
        host=request.build_absolute_uri(),
        status='ACCEPTED'
    )

    logging.debug('*** CPO/charger got request from OCPI Connector:')
    logging.debug(request.POST)

    # Todo: Add instructions for configuring charger endpoints
    force_result = request.GET.get('force_result')
    if force_result:
        result['status'] = force_result
        status = request.GET.get('force_status', default=409)

    # Pick a connector, any connector (for testing purposes)
    # noinspection PyUnresolvedReferences
    evse = Evse.objects.get(uid=request.POST.get('evse'))
    connector = evse.connectors.all()[0]
    result['connector'] = connector.uid

    return HttpResponse(json.dumps(result), status=status)


@csrf_exempt
def emsp_callback(request: WSGIRequest):
    """
    After the session start, a response is sent asynchronously
    to a dynamically specified callback URL on the eMSP server
    """

    data = json.loads(request.body.decode("utf8"))
    logging.debug('*** eMSP got response from charger/CPO:')
    logging.debug(data)
    return HttpResponse()


urls = [
    path('session/start/', session_start, name='simulate_session_start'),
    path('emsp/command_callback/', emsp_callback, name='emsp_callback'),
]
