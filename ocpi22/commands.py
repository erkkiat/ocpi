import uuid
from collections import OrderedDict
from urllib.parse import urljoin

from django.conf import settings
from django.db import transaction
from django.http import Http404
from icecream import ic
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.viewsets import GenericViewSet

from ocpi22.api import TokenSerializer, CommandTokenSerializer
from ocpi22.auth import OCPIPermission
from ocpi22.models import Session, Evse, Endpoint, CredentialsRole, Token
from ocpi22.sessions import create_session
from ocpi22.tasks import command_start
from ocpi22.util import OCPIResponse, Ocpi, ocpi_post

import pprint
pp = pprint.PrettyPrinter(indent=4).pprint


class CommandsSerializer(serializers.Serializer):
    response_url = serializers.URLField(
        label='URL that the CommandResult POST should be sent to. '
              'This URL might contain a unique ID to be able to distinguish between StartSession requests.'
    )
    token = CommandTokenSerializer(
        label='Token object the Charge Point has to use to start a new session. '
              'The Token provided in this request is authorized by the eMSP.'
    )
    location_id = serializers.CharField(
        label='Location.id of the Location (belonging to the CPO this request was sent to) '
              'on which a session is to be started.'
    )
    evse_uid = serializers.CharField(
        required=False, allow_blank=True,
        label='Optional EVSE.uid of the EVSE of this Location on which a session is to be started.'
    )
    authorization_reference = serializers.CharField(
        required=False, allow_blank=True,
        label='Reference to the authorization given by the eMSP, '
              'when given, this reference will be provided in the relevant Session and/or CDR.'
    )


class DisplayTextSerializer(serializers.Serializer):
    # Language Code ISO 639-1.
    language = serializers.CharField(max_length=2)

    # Text to be displayed to a end user. No markup, html etc. allowed.
    text = serializers.CharField(max_length=512)


class CommandResponse(serializers.Serializer):

    RESULT_OPTIONS = (
        ('NOT_SUPPORTED', 'Not supported'),             # The requested command is not supported by this CPO,
                                                        # Charge Point, EVSE etc.
        ('REJECTED', 'Rejected'),                       # Command request rejected by the CPO.
                                                        # (Session might not be from a customer
                                                        # of the eMSP that send this request)
        ('ACCEPTED', 'Accepted'),                       # Command request accepted by the CPO.
        ('UNKNOWN_SESSION', 'Session is not valid'),    # The Session in the requested command is not known by this CPO.
    )

    # Response from the CPO on the command request.
    result = serializers.ChoiceField(choices=RESULT_OPTIONS)

    # Timeout for this command in seconds. When the Result is not received within this timeout,
    # the eMSP can assume that the message might never be send.
    timeout = serializers.IntegerField()

    # Human-readable description of the result (if one can be provided), multiple languages can be provided.
    message = serializers.SerializerMethodField()

    @staticmethod
    def get_message(obj):
        return [
            dict(language=o['language'], text=o['text'])
            for o in obj['message']
        ]


class CommandResult(serializers.Serializer):

    RESULT_OPTIONS = (
        ('ACCEPTED', 'Accepted'),                               # Command request accepted by the Charge Point.
        ('CANCELED_RESERVATION', 'CPO cancelled reservation'),  # The Reservation has been canceled by the CPO.
        ('EVSE_OCCUPIED', 'EVSE is currently in use'),          # EVSE is currently occupied, another session is ongoing
                                                                # Cannot start a new session
        ('EVSE_INOPERATIVE', 'EVSE is inoperative'),            # EVSE is currently inoperative or faulted.
        ('FAILED', 'Command failed'),                           # Execution of the command failed at the Charge Point.
        ('NOT_SUPPORTED', 'Command is not supported'),          # The requested command is not supported
                                                                # by this Charge Point, EVSE etc.
        ('REJECTED', 'Command rejected'),                       # Command request rejected by the Charge Point.
        ('TIMEOUT', 'Command timeout'),                         # Command request timeout, no response received
                                                                # from the Charge Point in a reasonable time.
        ('UNKNOWN_RESERVATION', 'No matching reservation'),     # The Reservation in the requested command
                                                                # is not known by this Charge Point.
    )

    # Result of the command request as sent by the Charge Point to the CPO.
    result = serializers.ChoiceField(choices=RESULT_OPTIONS)

    # Human-readable description of the reason (if one can be provided), multiple languages can be provided.
    message = serializers.SerializerMethodField()

    @staticmethod
    def get_message(obj):
        pp(obj)
        return [
            OrderedDict(language=o['language'], text=o['text'])
            for o in obj['message']
        ]


class CommandsViewSet(mixins.ListModelMixin, GenericViewSet):
    root_view_name = 'commands'
    queryset = Session.objects.none()  # Users who can access Sessions can issue Commands also
    serializer_class = CommandsSerializer
    permission_classes = [OCPIPermission]

    @transaction.atomic
    @action(methods=['GET', 'POST'], detail=False, url_name='start-session', url_path='START_SESSION')
    def start_session(self, request):
        try:
            serializer = self.serializer_class(data=request.data)
            if serializer.is_valid():
                result = 'ACCEPTED'
                token = serializer.data.get('token', '')
                session: Session = create_session(
                    location_id=serializer.data['location_id'],
                    evse_id=serializer.data.get('evse_uid', ''),
                    connector_id=serializer.data.get('connector_id'),
                    authorization_reference=serializer.data.get('authorization_reference'),
                    ad_hoc_token=token,
                    authorize=False
                    # When eMSP sends a SESSION_START, they are responsible for validating their Token
                )

                command_start.delay(
                    serializer.data, session.uid,
                    update_url=request.build_absolute_uri(reverse('session-update', args=[session.uid])),
                    url=request.build_absolute_uri(reverse('simulate_session_start')))
                response_serializer = CommandResponse(
                    instance=dict(
                        result=result,
                        timeout=120,
                        message=[
                            dict(language='EN', text='Preparing to charge'),
                            dict(language='FI', text='Latausta valmistellaan')
                        ]
                    ))
                return OCPIResponse(response_serializer.data)
        except (NotFound, Http404, KeyError) as e:
            return OCPIResponse(None, status_message=str(e),
                                http_status=status.HTTP_400_BAD_REQUEST,
                                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)
        return OCPIResponse(serializer.errors, status_message='Please check your request parameters',
                            http_status=status.HTTP_400_BAD_REQUEST,
                            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    def get_view_name(self):
        return 'Commands'

    def list(self, request, *args, **kwargs):
        return Response(dict(
            start_session=request.build_absolute_uri(reverse('commands-start-session')),
        ))


def get_our_first_token():
    try:
        return Token.objects.filter(country_code=settings.COUNTRY_CODE, party_id=settings.PARTY_ID)[0]
    except IndexError:
        raise ValueError('Please create a Token first.')


def find_endpoint(country_code, party_id, identifier, endpoint_role) -> Endpoint:
    for role in CredentialsRole.objects.filter(country_code=country_code, party_id=party_id):
        for credentials in role.credentials.all():
            # noinspection PyUnresolvedReferences
            endpoints = credentials.endpoints.filter(identifier=identifier, role=endpoint_role)
            if endpoints.count():
                return endpoints[0]


def send_start_command(request, evse: Evse, token: Token) -> Response:
    if evse.location.party() != f'{settings.COUNTRY_CODE}*{settings.PARTY_ID}':
        country_code = evse.location.country_code
        party_id = evse.location.party_id
        # noinspection PyUnresolvedReferences

        endpoint = find_endpoint(country_code, party_id, Endpoint.COMMANDS, Endpoint.RECEIVER)
        if endpoint:
            print(f'*** Sending start command for {evse.location.name}.')
            data=dict(
                    response_url=request.build_absolute_uri('/'),
                    token=TokenSerializer(token).data,
                    location_id=evse.location.uid,
                    evse_uid=evse.uid,
                    authorization_reference=uuid.uuid4().hex,
            )
            ic(data)
            ic(endpoint.url)
            return ocpi_post(urljoin(f'{endpoint.url}/', 'START_SESSION'), endpoint.get_token_base64(),
                             data=data)
        else:
            print(f'Unable to find endpoint for {evse.location.party()}.')
            return Response()
    else:
        print(f'Not sending start command to ourself.')
        return Response()
