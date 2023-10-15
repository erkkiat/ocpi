from datetime import timedelta
from functools import wraps

import pytz
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.utils import timezone
from django.utils.datetime_safe import datetime
from rest_framework import status
from rest_framework.exceptions import APIException

from certification.decorators import certification_step_list
from certification.serializers import StartSessionSerializer
from ocpi22.choices import CERTIFICATION_TOPIC_DICT, CERTIFICATION_TOPIC_CHOICES, OcpiRolesEnum, OcpiModuleEnum
from ocpi22.commands.commands import send_start_command, send_stop_command
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session
from ocpi22.util import fetch_object
from ocpiconnector import settings
from ocpiconnector.management.commands.exchange_credentials import get_our_roles
from ocpiconnector.ocpi_identities import get_our_credentialsrole
from util import reverse


def certification_disabled(request, template_name='certification/disabled.html'):
    """Show the certification disabled page to the user"""

    return render(request, template_name)


def certification_home(request, template_name='certification/home.html'):
    """Show the certification progress to the user"""

    if not settings.CERTIFICATION_MODE:
        return certification_disabled(request)

    def get_data(topic):
        steps = certification_step_list[topic]
        # Retrieve the status of each step from persistent storage
        list(map(lambda x: x.retrieve(), steps))  # Trigger the lazy bastard using list
        return {'heading': CERTIFICATION_TOPIC_DICT[topic], 'steps': steps}

    items = [get_data(x[0]) for x in CERTIFICATION_TOPIC_CHOICES]

    return render(
        request,
        template_name,
        context=dict(
            certification_items=items
        )
    )


def certification_exception_handler(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (APIException, Location.DoesNotExist, Evse.DoesNotExist, Connector.DoesNotExist) as e:
            request = args[0]
            messages.error(request, f'Error: {e}')
            return HttpResponseRedirect(request.path)

    return wrapper


@certification_exception_handler
def start_session(request):
    """
    Send a START_SESSION remote command
    """
    if request.method == 'POST':
        serializer = StartSessionSerializer(data=request.POST.dict())
        if serializer.is_valid():
            request.version = '2.2.1'
            authorization_reference = f'A-{datetime.now().strftime("%Y-%m-%dT%H-%M-%SZ")}'
            result = send_start_command(request, evse=serializer.validated_data.get('evse'),
                                        token='TOKEN-123',
                                        connector_id=serializer.validated_data.get('connector').uid,
                                        authorization_reference=authorization_reference)
            if result.status_code == status.HTTP_200_OK:
                messages.success(request, 'START_SESSION command sent successfully')
            else:
                messages.error(request, f'Error sending StartSession command: {result.text}')
        else:
            messages.error(request, f'Error sending StartSession command: {serializer.errors}')
        return HttpResponseRedirect(request.path)


@certification_exception_handler
def stop_session(request):
    """
    Send a STOP_SESSION remote command
    """
    if request.method == 'POST':
        session = Session.objects.get(uid=request.POST.get('session'))
        if session and session.status == Session.ACTIVE:
            request.version = '2.2.1'
            result = send_stop_command(session)
            if result.status_code == status.HTTP_200_OK:
                messages.success(request, 'STOP_SESSION command sent successfully')
            else:
                messages.error(request, f'Error sending StopSession command: {result.text}')
                # Todo: Fetch missing Sessions
                # fetch_object(session.uid, party=session.ocpi_master.party, ocpi_module=OcpiModuleEnum.SESSIONS)
        else:
            messages.error(request, f'Error sending StopSession command: {serializer.errors}')
        return HttpResponseRedirect(request.path)


@certification_exception_handler
def sessions(request, template_name='certification/start_session.html'):
    """Show the certification progress to the user"""

    locations = Location.objects.exclude(ocpi_master=get_our_credentialsrole(OcpiRolesEnum.CPO))
    selected_location = request.GET.get('location', '')
    selected_evse = request.GET.get('evse', '')
    selected_connector = request.GET.get('connector', '')

    if request.method == 'POST':
        if 'start' in request.POST:
            return start_session(request)
        elif 'stop' in request.POST:
            return stop_session(request)

    evses = Evse.objects.filter(location__uid=selected_location) if selected_location else None
    connectors = evses.get(uid=selected_evse).connectors.all() if selected_evse else None

    now = datetime.now(pytz.utc)

    return render(
        request,
        template_name,
        context=dict(
            locations=locations,
            selected_location=selected_location,
            evses=evses,
            selected_evse=selected_evse,
            connectors=connectors,
            selected_connector=selected_connector,
            sessions=Session.objects.filter(
                status=Session.ACTIVE  # , start_date_time__gte=now-timedelta(days=1)
            ).order_by('-start_date_time')
        )
    )
