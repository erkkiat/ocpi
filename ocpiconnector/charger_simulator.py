import json

from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from pprint import PrettyPrinter
pp = PrettyPrinter(indent=4).pprint


@csrf_exempt
def session_start(request):
    status = 200
    result = dict(
        mode='SIMULATOR',
        host=request.build_absolute_uri(),
        status='ACCEPTED'
    )
    # Todo: Add instructions for configuring charger endpoints
    force_result = request.GET.get('force_result')
    if force_result:
        result['status'] = force_result
        status = request.GET.get('force_status', default=500)
    return HttpResponse(json.dumps(result), status=status)


@csrf_exempt
def emsp_callback(request: WSGIRequest):
    data = json.loads(request.body.decode("utf8"))
    pp('Got response from CPO:')
    pp(data)
    return HttpResponse()


urls = [
    path('session/start/', session_start, name='simulate_session_start'),
    path('emsp/command_callback/', emsp_callback, name='emsp_callback'),
]
