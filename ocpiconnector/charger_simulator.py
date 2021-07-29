from django.http import HttpResponse
from django.urls import path


def session_start(request):
    signature = f' (from simulator at {request.build_absolute_uri()}) - to configure your charger endpoints ...'
    # Todo: Add instructions for configuring charger endpoints
    if request.GET.get('error'):
        return HttpResponse('ERROR (as requested) ' + signature, status=500)
    if request.GET.get('busy'):
        return HttpResponse('CHARGER BUSY (as requested)' + signature, status=503)
    return HttpResponse('CHARGER OK' + signature)


urls = [
    path('session/start/', session_start, name='simulate_session_start'),
]
