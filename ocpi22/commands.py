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

from ocpi22.api import TokenSerializer, CommandTokenSerializer, LocationIdSerializer
from ocpi22.auth import OCPIPermission
from ocpi22.cpo_api import CHARGER
from ocpi22.models.credentials import CredentialsRole, Endpoint
from ocpi22.models.location import Evse
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.sessions import create_session
from ocpi22.tasks import command_start
from ocpi22.ocpi_util import ocpi_post, OCPIResponse, Ocpi

import pprint
pp = pprint.PrettyPrinter(indent=4).pprint


class StartSessionSerializer(serializers.Serializer):
    response_url = serializers.URLField(
        help_text='URL that the CommandResult POST should be sent to. '
                  'This URL might contain a unique ID to be able to distinguish between StartSession requests.'
    )
    token = CommandTokenSerializer(
        help_text='Token object the Charge Point has to use to start a new session. '
                  'The Token provided in this request is pre-authorized by the eMSP.'
    )
    location_id = serializers.CharField(
        max_length=36,
        help_text='Location.id of the Location (belonging to the CPO this request was sent to) '
                  'on which a session is to be started.'
    )
    evse_uid = serializers.CharField(
        max_length=36,
        required=False, allow_blank=True,
        help_text='Optional EVSE.uid of the EVSE of this Location on which a session is to be started.'
    )
    authorization_reference = serializers.CharField(
        max_length=36,
        required=False, allow_blank=True,
        help_text='Reference to the authorization given by the eMSP, '
                  'when given, this reference will be provided in the relevant Session and/or CDR.'
    )


class StopSessionSerializer(serializers.Serializer):
    response_url = serializers.URLField(
        help_text='URL that the CommandResult POST should be sent to. '
                  'This URL might contain a unique ID to be able to distinguish between StopSession requests.'
    )
    session_id = serializers.CharField(
        max_length=36,
        help_text='Session.id of the Session that is requested to be stopped.'
    )


class UnlockConnectorSerializer(serializers.Serializer):
    response_url = serializers.URLField(
        help_text='URL that the CommandResult POST should be sent to. '
                  'This URL might contain an unique ID to be able to distinguish between UnlockConnector requests.'
    )
    location_id = LocationIdSerializer(
        max_length=36,
        help_text='Location.id of the Location (belonging to the CPO this request is send to) '
                  'of which it is requested to unlock the connector.'
    )
    evse_uid = serializers.CharField(
        max_length=36,
        required=False, allow_blank=True,
        help_text='EVSE.uid of the EVSE of this Location of which it is requested to unlock the connector.'
    )
    connector_id = serializers.CharField(
        max_length=36,
        help_text='Connector.id of the Connector of this Location of which it is requested to unlock.'
    )


class DisplayTextSerializer(serializers.Serializer):
    # Language Code ISO 639-1.
    language = serializers.CharField(max_length=2)

    # Text to be displayed to a end user. No markup, html etc. allowed.
    text = serializers.CharField(max_length=512)


class CommandResponse(serializers.Serializer):
    NOT_SUPPORTED = 'NOT_SUPPORTED'
    REJECTED = 'REJECTED'
    ACCEPTED = 'ACCEPTED'
    UNKNOWN_SESSION = 'UNKNOWN_SESSION'

    RESULT_OPTIONS = (
        ('NOT_SUPPORTED', 'Not supported'),  # The requested command is not supported by this CPO,
        # Charge Point, EVSE etc.
        ('REJECTED', 'Rejected'),  # Command request rejected by the CPO.
        # (Session might not be from a customer
        # of the eMSP that send this request)
        ('ACCEPTED', 'Accepted'),  # Command request accepted by the CPO.
        ('UNKNOWN_SESSION', 'Session is not valid'),  # The Session in the requested command is not known by this CPO.
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


class CommandsViewSet(GenericViewSet):
    # root_view_name = 'commands'
    # noinspection PyUnresolvedReferences
    queryset = Session.objects.none()  # Users who can access Sessions can issue Commands also
    permission_classes = [OCPIPermission]

    def get_serializer_class(self):
        if not hasattr(self, 'action_map'): return serializers.Serializer
        # ic(self.action_map['post'])
        serializer = dict(
            start_session=StartSessionSerializer,
            stop_session=StopSessionSerializer,
            unlock_connector=UnlockConnectorSerializer,
        ).get(self.action_map['post'])
        return serializer

    # def options(self, request, *args, **kwargs):
    #     ic(request, args, kwargs)
    #     return Response(
    #         dict(
    #             helptext='Please see OPTIONS for specific commands, such as START_SESSION or UNLOCK_CONNECTOR'
    #         )
    #     )

    def get_view_name(self):
        # ic(self.kwargs if hasattr(self, 'kwargs') else 'N/A')
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'Command {self.kwargs.get("uid")}'
        if self.name:
            return f'{self.name.capitalize()}'
        return f'Commands'

    @transaction.atomic
    @action(methods=['GET', 'POST'], detail=False, url_name='start-session', url_path='START_SESSION')
    def start_session(self, request):
        if not request.data:
            return OCPIResponse(status_message='Please see OPTIONS to learn what you can POST at this endpoint')
        try:
            serializer = StartSessionSerializer(data=request.data)
            if serializer.is_valid():
                result = 'ACCEPTED'
                token = serializer.data.get('token', '')
                connector_id = serializer.data.get('connector_id', None)
                evse_uid = serializer.data.get('evse_uid', '')
                session: Session = create_session(
                    location_id=serializer.data['location_id'],
                    evse_id=evse_uid,
                    connector_id=connector_id,
                    authorization_reference=serializer.data.get('authorization_reference'),
                    ad_hoc_token=token,
                    authorize=False
                    # When eMSP sends a SESSION_START, they are responsible for validating their Token
                )

                connector_id_from_charger = CHARGER.remote_start_transaction(token.get('uid'), session.evse)
                if not connector_id_from_charger:
                    return Response(dict(error=f'Unable to start session on charger at this time',
                                         status=status.HTTP_406_NOT_ACCEPTABLE))

                command_start.delay(
                    serializer.data, session.uid,
                    update_url=request.build_absolute_uri(reverse('session-update', args=[session.uid])),
                    url=request.build_absolute_uri(reverse('simulate_session_start')))  # Todo: use actual callback
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

    @transaction.atomic
    @action(methods=['GET', 'POST'], detail=False, url_path='STOP_SESSION')
    def stop_session(self, request):
        if not request.data:
            return OCPIResponse(status_message='Please see OPTIONS to learn what you can POST at this endpoint')
        try:
            serializer = StopSessionSerializer(data=request.data)
            if serializer.is_valid():
                result = 'ACCEPTED'
                session: Session = Session.get_if_exists(uid=serializer.data.get('session_id'))

                if not CHARGER.remote_stop_transaction(session):
                    return Response(dict(error=f'Unable to stop session on charger at this time',
                                         status=status.HTTP_406_NOT_ACCEPTABLE))

                session.status = Session.COMPLETED
                session.save()
                # Cdr.session_changed(session)

                command_start.delay(
                    serializer.data, session.uid,
                    update_url=request.build_absolute_uri(reverse('session-update', args=[session.uid])),
                    url=request.build_absolute_uri(reverse('simulate_session_start')))  # Todo: use actual callback
                response_serializer = CommandResponse(
                    instance=dict(
                        result=result,
                        timeout=120,
                        message=[
                            dict(language='EN', text='Stopping charging'),
                            dict(language='FI', text='Lataus päättyy')
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

    @transaction.atomic
    @action(methods=['GET', 'POST'], detail=False, url_path='UNLOCK_CONNECTOR')
    def unlock_connector(self, request):
        if not request.data:
            return OCPIResponse(status_message='Please see OPTIONS to learn what you can POST at this endpoint')
        try:
            serializer = UnlockConnectorSerializer(data=request.data)
            if serializer.is_valid():
                result = 'ACCEPTED'
                if not CHARGER.unlock_connector(**serializer.data):
                    return OCPIResponse(status_message=f'Unable to unlock connector at this time',
                                        http_status=status.HTTP_404_NOT_FOUND,
                                        status_code=Ocpi.ClientError.UNKNOWN_LOCATION)

                response_serializer = CommandResponse(
                    instance=dict(
                        result=result,
                        timeout=120,
                        message=[
                            dict(language='EN', text='Unlocking connector'),
                            dict(language='FI', text='Liittimen lukitus vapautetaan')
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

    def list(self, request, *args, **kwargs):
        return Response(dict(
            start_session=request.build_absolute_uri(reverse('commands-start-session')),
            stop_session=request.build_absolute_uri(reverse('commands-stop-session')),
            unlock_connector=request.build_absolute_uri(reverse('commands-unlock-connector')),
        ))


def get_our_first_token():
    our_country_code, our_party_id = Token.get_owner_party().split('*')

    try:
        return Token.objects.filter(country_code=our_country_code, party_id=our_party_id)[0]
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
    country_code = evse.location.country_code
    party_id = evse.location.party_id
    # noinspection PyUnresolvedReferences

    endpoint = find_endpoint(country_code, party_id, Endpoint.COMMANDS, Endpoint.RECEIVER)
    if endpoint:
        print(f'*** Sending start command for {evse.location.name}.')
        data = dict(
            response_url=request.build_absolute_uri('/'),
            token=TokenSerializer(token).data,
            location_id=evse.location.uid,
            evse_uid=evse.uid,
            authorization_reference=uuid.uuid4().hex,
        )
        return ocpi_post(urljoin(f'{endpoint.url}/', 'START_SESSION'), endpoint.get_token_base64(),
                         data=data)
    else:
        print(f'Unable to find endpoint for {evse.location.party()}.')
        return Response()


def send_stop_command(request, session: Session) -> Response:
    country_code = session.location.country_code
    party_id = session.location.party_id
    # noinspection PyUnresolvedReferences

    endpoint = find_endpoint(country_code, party_id, Endpoint.COMMANDS, Endpoint.RECEIVER)
    if endpoint:
        print(f'*** Sending stop command for {session}.')
        data = dict(
            response_url=request.build_absolute_uri('/'),
            session_id=session.uid,
        )
        ic(data)
        ic(endpoint.url)
        return ocpi_post(urljoin(f'{endpoint.url}/', 'STOP_SESSION'), endpoint.get_token_base64(),
                         data=data)
    else:
        print(f'Unable to find endpoint for {session.party()}.')
        return Response()
