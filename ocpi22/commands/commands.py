import pytz
from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt

import ocpi22.logging as logging

from dataclasses import dataclass
from datetime import timedelta
from typing import Union, Optional
from urllib.parse import urljoin

from django.conf import settings
from django.utils.datetime_safe import datetime
from rest_framework import serializers, status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response

from certification.decorators import certification_step
from ocpi22.commands.cpo_simulator import start_simulated_session
from ocpi22.decorators import requires_sender_role
from ocpi22.msp.models import Authorization
from ocpi22.tasks import send_ocpi_request
from ocpiconnector.exception_handler import ocpi_exception_handler
from util import reverse
from rest_framework.viewsets import GenericViewSet

from ocpi22.util import OCPIVersioning, generate_random_token
from ocpi22.cpo.api import close_active_sessions_for_evse
from ocpi22.webhooks import send_to_webhook
from ocpi22.ocpi.serializers import TokenSerializer
from ocpi22.ocpi.auth import OCPIPermission
from ocpi22.choices import OcpiModuleEnum, OcpiRolesEnum, MessageTexts, TokenType
from ocpi22.commands.serializers import StartSessionSerializer, StopSessionSerializer, UnlockConnectorSerializer, \
    CommandResponse, CommandResultSerializer, ReserveNowSerializer
from ocpi22.cpo.serializers import CPOStartWebhookSerializer, CPOStopWebhookSerializer, \
    CPOReserveNowWebhookSerializer
from ocpi22.models.location import Evse, Location
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.rendering import RENDERERS
from ocpi22.routing import find_route, Route
from ocpi22.sessions.util import create_session
from ocpi22.ocpi.util import ocpi_post, OCPIResponse, Ocpi, generate_auth_reference, options_message
from ocpi22.ocpi.util_party import get_sender_party

from ocpi22.tokens.util import construct_adhoc_token, get_token_id, get_token_type
from ocpiconnector.ocpi_identities import get_our_party, Party, ocpi_platform
from ocpi22.util import build_absolute_uri, command_store
from ocpi22.logging import log_error


@dataclass(eq=True)
class ResponseData:
    ocpi_status: int
    result: str
    http_status: int
    message: list
    timeout: int


class CommandsViewSet(GenericViewSet):
    # root_view_name = 'commands'
    queryset = Session.objects.none()  # Users who can access Sessions can issue Commands also
    versioning_class = OCPIVersioning
    permission_classes = [OCPIPermission]
    renderer_classes = RENDERERS

    def get_serializer_class(self):
        if not hasattr(self, 'action_map'):
            return serializers.Serializer
        # ic(self.action_map['post'])
        serializer = dict(
            start_session=StartSessionSerializer,
            stop_session=StopSessionSerializer,
            unlock_connector=UnlockConnectorSerializer,
            reserve_now=ReserveNowSerializer,
            command_result=CommandResultSerializer,
        ).get(self.action_map.get('post'), serializers.Serializer)
        return serializer

    def get_view_name(self):
        # ic(self.kwargs if hasattr(self, 'kwargs') else 'N/A')
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'Command {self.kwargs.get("uid")}'
        if self.name:
            return f'{self.name.capitalize()}'
        return f'Commands'

    @staticmethod
    def _get_sender_party(request) -> Party:
        billed_to = get_sender_party(request.META)
        assert isinstance(billed_to, Party) and len(str(billed_to)) == 6, \
            f'Billed_to needs to be set with party ID: {billed_to}.' \
            f' (You need to be using Credentials and OCPI routing headers for the connection.)'
        return billed_to

    error_response = ResponseData(ocpi_status=2000, result=CommandResponse.REJECTED,
                                  http_status=status.HTTP_503_SERVICE_UNAVAILABLE, message=[], timeout=60)

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.EMSP)
    @certification_step(OcpiModuleEnum.COMMANDS, 'Send a START_SESSION command to the CPO')
    def start_session(self, request, **_kwargs):
        return self.process_remote_command(request,
                                           command_serializer=StartSessionSerializer,
                                           webhook_serializer=CPOStartWebhookSerializer,
                                           command_prefix='START',
                                           extra_actions=self.start_session_extra_actions)

    @staticmethod
    def create_session(request, token, connector_id, billed_to, evse_uid, serializer, **_kwargs):
        params = serializer.validated_data.copy()
        params.update(
            dict(
                ad_hoc_token=token,
                billed_to=billed_to,
                authorization_method=Session.COMMAND,
                credentials=request.credentials,
                connector_id=connector_id,
            )
        )
        params.pop('token')

        close_active_sessions_for_evse(evse_uid)
        session: Session = create_session(**params)

        return session

    def reserve_now_extra_actions(self, request, session, **kwargs):
        if not session:
            session = self.create_session(request, **kwargs)
            logging.info(f'Created reservation session {session.uid} based on remote command from MSP.')
        else:
            logging.info(f'Found an existing session {session.uid}.')

    def start_session_extra_actions(self, request, session, **kwargs):
        if not session:
            session = self.create_session(request, **kwargs)
            logging.info(f'Created session {session.uid} based on remote command from MSP.')
        else:
            logging.info(f'Found an existing session {session.uid}.')

        # Reservation may have started earlier, but charging session starts now
        session.start_date_time = datetime.utcnow().replace(tzinfo=pytz.utc)
        session.save(update_fields=['start_date_time'])

        if settings.CPO_SIMULATOR:
            start_simulated_session(session, **kwargs)

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.EMSP)
    @certification_step(OcpiModuleEnum.COMMANDS, 'Send a RESERVE_NOW command to the CPO')
    def reserve_now(self, request, **_kwargs):
        # TODO: If this Token is of type RFID, the CPO SHALL NOT do a realtime authorization at the eMSP for
        #  this Token at the given EVSE/Charge Point within 15 minutes after having received this ReserveNow.

        return self.process_remote_command(request,
                                           command_serializer=ReserveNowSerializer,
                                           webhook_serializer=CPOReserveNowWebhookSerializer,
                                           command_prefix='RESERVE',
                                           extra_actions=self.reserve_now_extra_actions)

    @ocpi_exception_handler
    @csrf_exempt
    def hubresponse(self, request, command_id, version='2.2.1'):
        if not ocpi_platform.is_hub:
            return OCPIResponse(status_code=Ocpi.ServerError.GENERIC_SERVER_ERROR,
                                http_status=status.HTTP_404_NOT_FOUND)
        command_data = command_store[command_id]
        ic(version, command_data)
        if command_data:
            route_dict = command_data.get('route_back')
            print(f'{route_dict=}')
            route: Route = Route(**route_dict)
            our_hub_party: Party = get_our_party(OcpiRolesEnum.HUB)

            if route:
                response = send_ocpi_request(  # Todo: How about just data, route as parameters?
                    request.data, url=route.url, token_base64=route.token_base64,
                    to_country_code=route.to.get('country_code'),
                    to_party_id=route.to.get('party_id'),
                    from_country_code=our_hub_party.country_code,
                    from_party_id=our_hub_party.party_id,
                    method='post', credentials_id=route.credentials_id,
                    title='Hub response to CPO'
                )
                ic(response)
                status_code = {
                    200: Ocpi.OK,
                }.get(response.get('status_code', 400), Ocpi.ServerError.GENERIC_SERVER_ERROR)
                return OCPIResponse(status_code=status_code, http_status=response.get('status_code'))
        return OCPIResponse(status_code=Ocpi.ServerError.GENERIC_SERVER_ERROR, http_status=status.HTTP_404_NOT_FOUND)

    # Exception handling is done in the calling method, no need for it here
    def process_remote_command(self, request, command_serializer, webhook_serializer, command_prefix,
                               extra_actions=None):

        if not getattr(request, 'data', None):
            return OCPIResponse({'status_message': options_message}, status=status.HTTP_400_BAD_REQUEST)
        billed_to = str(self._get_sender_party(request))
        serializer = command_serializer(data=request.data, context={'request': request, 'version': request.version})
        if serializer.is_valid():

            token = serializer.validated_data.get('token', '')
            authorization_reference = serializer.validated_data.get('authorization_reference')
            session_id = serializer.validated_data.get('session_id')

            session: Session = Session.get_if_exists(
                Q(authorization_reference=authorization_reference) | Q(cdr_token_uid=token) | Q(uid=session_id)
            )

            if session and session.status == Session.COMPLETED:
                raise APIException(f'Unable to complete command {command_prefix} '
                                   'because the session has already been completed.')

            ocpi_response_url = serializer.validated_data.pop('response_url')
            token_id = session.cdr_token_uid if session else get_token_id(token)
            evse_uid = session.evse.uid if session else serializer.validated_data.get('evse_uid')
            connector_id = session.connector.uid if session else serializer.validated_data.get('connector_id')

            # Store the command for use during the next {settings.REMOTE_COMMAND_EXPIRATION} seconds
            command_id = authorization_reference or generate_random_token()
            command_store[command_id] = serializer.validated_data

            # The worst scenario is this
            ocpi_status = 2000
            http_status = status.HTTP_503_SERVICE_UNAVAILABLE
            timeout = 60
            status_message = ''
            ocpi_result = CommandResponse.REJECTED

            # Prepare the command for CPO management system
            initial_data = dict(
                response_url=build_absolute_uri(reverse('chargepoint-remote-command-result',
                                                        args=(command_id,))),
                token_id=token_id,
                token_type=session.cdr_token_type if session else get_token_type(token, TokenType.APP_USER),
                authorization_reference=session.authorization_reference if session else authorization_reference,
                auth_method=Session.COMMAND,
                from_party=str(request.ocpi_party.party),
                evse_id=evse_uid,
                connector_id=connector_id,
                billed_to=billed_to,
            )
            initial_data.update(**serializer.validated_data)

            if settings.PERFORMANCE_TEST or settings.CPO_SIMULATOR:
                data = dict(timeout=90, result='ACCEPTED')
            else:
                data = send_to_webhook(initial_data, webhook_serializer)
            if not data:
                logging.error(f'Unable to connect to CPMS webhook at {webhook_serializer.URL}.')
                return OCPIResponse(None,
                                    status_message=f'Unable to complete {command_prefix} '
                                                   'due to a communication error.',
                                    http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                                    status_code=Ocpi.ServerError.GENERIC_SERVER_ERROR)

            timeout = int(data.get('timeout', timeout))
            result = data.get('result', CommandResponse.REJECTED).upper()
            logging.info(f'Result from charger for command {command_prefix}: {result}')
            message = MessageTexts.get(
                f'{command_prefix}_{result}',  # E.g. try to get response message for START_<result>
                MessageTexts.get(
                    result,  # Then just for <result>
                    MessageTexts.get('DEFAULT_CHARGER_ERROR_TEXT')))  # Or just use the default
            if result == CommandResponse.ACCEPTED:
                if extra_actions:
                    extra_actions(request, session, ocpi_response_url=ocpi_response_url,
                                  serializer=serializer, **initial_data)

                ocpi_result = CommandResponse.ACCEPTED
                ocpi_status = Ocpi.OK
                http_status = status.HTTP_200_OK

            response_serializer = CommandResponse(
                data=dict(result=ocpi_result, timeout=timeout, message=message)
            )
            assert response_serializer.is_valid(), \
                f'Internal error, CommandResponse is not properly formatted: {response_serializer.errors}'
            return OCPIResponse(response_serializer.data, status_code=ocpi_status, http_status=http_status,
                                status_message=status_message)
        else:
            return OCPIResponse(serializer.errors, status_message='Please check your request parameters',
                                http_status=status.HTTP_400_BAD_REQUEST,
                                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.EMSP)
    @certification_step(OcpiModuleEnum.COMMANDS, 'Send a STOP_SESSION command to the CPO')
    def stop_session(self, request, **_kwargs):
        return self.process_remote_command(request,
                                           command_serializer=StopSessionSerializer,
                                           webhook_serializer=CPOStopWebhookSerializer,
                                           command_prefix='STOP',
                                           extra_actions=self.stop_session_extra_actions)

    @staticmethod
    def stop_session_extra_actions(_request, session: Session, **_kwargs):
        """
        This method is called from the process_remote_command
        """
        session.status = Session.COMPLETED
        session.end_date_time = datetime.utcnow().replace(tzinfo=pytz.utc)
        session.save(update_fields=['status', 'end_date_time'])

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.EMSP)
    @certification_step(OcpiModuleEnum.COMMANDS, 'Send an UNLOCK_CONNECTOR command to the CPO')
    def unlock_connector(self, request, **_kwargs):
        if not request.data:
            return OCPIResponse({'status_message': options_message}, status=status.HTTP_400_BAD_REQUEST)
        serializer = UnlockConnectorSerializer(data=request.data)
        if serializer.is_valid():
            result = 'ACCEPTED'

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
        else:
            return OCPIResponse(serializer.errors, status_message='Please check your request parameters',
                                http_status=status.HTTP_400_BAD_REQUEST,
                                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    @ocpi_exception_handler
    @certification_step(OcpiModuleEnum.COMMANDS, 'Send a CommandResult to the eMSP')
    def command_result(self, request, command=None, command_id=None, version='2.2.1'):
        """
        This is only used by eMSP for receiving the final result for remote command
        """
        if not request.data:
            return OCPIResponse({'status_message': options_message}, status=status.HTTP_400_BAD_REQUEST)
        session = Session.objects.filter(authorization_reference=command_id)
        authorization = Authorization.objects.filter(authorization_reference=command_id)
        if not session.exists() and not authorization:
            return OCPIResponse('Session not found', status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                                http_status=status.HTTP_400_BAD_REQUEST)
        if session.count() > 1:
            logging.error(f'Multiple Sessions found with the same authorization reference {command_id}')

        serializer = CommandResultSerializer(data=request.data)
        if serializer.is_valid():
            result = serializer.validated_data.get('result')
            message = serializer.validated_data.get('message')
            session.update(message=message)
            logging.info(f'Received CommandResult {result} and '
                         f'message {message or "N/A"} for command {command} ID {command_id}')
            # Todo: Embed any error or success text to the Session status response
            return OCPIResponse(
                status_message='Command result received, thank you!',
                data=dict(command_id=command_id))
        return OCPIResponse(serializer.errors, status_message='Please check your request parameters',
                            http_status=status.HTTP_400_BAD_REQUEST,
                            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    @staticmethod
    @ocpi_exception_handler
    def list(request, *_args, **_kwargs):
        # ic(request.version)
        return Response(dict(
            start_session=request.build_absolute_uri(reverse('commands-start-session', request=request)),
            stop_session=request.build_absolute_uri(reverse('commands-stop-session', request=request)),
            unlock_connector=request.build_absolute_uri(reverse('commands-unlock-connector', request=request)),
            reserve_now=request.build_absolute_uri(reverse('commands-reserve-now', request=request)),
            # command_result=request.build_absolute_uri(reverse('commands-command-result')),
        ))


def send_start_command(request, evse: Evse, token: Union[Token, str], connector_id=None, contract_id='',
                       authorization_reference: str = None) -> Response:
    """
    As an eMSP we send an OCPI Command START_SESSION to the CPO
    """
    country_code = evse.location.ocpi_master.country_code
    party_id = evse.location.ocpi_master.party_id

    route: Route = find_route(Party(country_code, party_id), OcpiModuleEnum.COMMANDS)
    if route:
        logging.info(f'*** Sending start command for {evse.location.name} to {route.url}.')
        if not isinstance(token, Token):
            token = construct_adhoc_token(token, contract_id=contract_id)
        token_data = TokenSerializer(token).data
        data = dict(
            response_url=build_absolute_uri(
                reverse('commands-command-result', args=("start", authorization_reference,))
            ),
            token=token_data,
            location_id=evse.location.uid,
            evse_uid=evse.uid,
            connector_id=connector_id,
            authorization_reference=authorization_reference,
        )
        if route.version == '2.2':
            data.pop('connector_id', None)
        serializer = StartSessionSerializer(data=data)
        if not serializer.is_valid():
            logging.error('Malformed outbound data in send_start_command() (system bug)')
            logging.error(serializer.errors)
            raise ValidationError('Malformed outbound data (system bug)')
        return ocpi_post(urljoin(f'{route.url}/', 'START_SESSION'), route.token_base64,
                         to=Party(country_code, party_id),
                         sender=get_our_party(OcpiRolesEnum.EMSP),
                         data=serializer.data)
    else:
        message = f"Cannot find a route for START_SESSION to {evse.location.party()}"
        log_error(request, message)
        raise APIException(message)


def send_reserve_command(request, location: Location, evse: Evse, token: Union[Token, str], reservation_id,
                         connector_id=None, contract_id='', expiration=settings.MAXIMUM_RESERVATION) -> Response:
    """
    As an eMSP we send an OCPI Command RESERVE_NOW to the CPO
    """
    country_code = evse.location.ocpi_master.country_code
    party_id = evse.location.ocpi_master.party_id

    route: Route = find_route(Party(country_code, party_id), OcpiModuleEnum.COMMANDS)
    if route:
        logging.info(f'*** Sending reserve command for {evse.location.name} to {route.url}.')
        if not isinstance(token, Token):
            token = construct_adhoc_token(token, contract_id=contract_id)
        token_data = TokenSerializer(token).data
        authorization_reference = generate_auth_reference()
        if evse.location != location:
            raise Evse.DoesNotExist(f'The EVSE {evse.evse_id} is not at location {location.uid}')
        data = dict(
            response_url=build_absolute_uri(
                reverse('commands-command-result', args=("reserve", authorization_reference,))
            ),
            token=token_data,
            location_id=location.uid,
            evse_uid=evse.uid,
            connector_id=connector_id,
            authorization_reference=authorization_reference,
            expiry_date=datetime.now() + timedelta(seconds=expiration),
            reservation_id=reservation_id
        )
        serializer = ReserveNowSerializer(data=data)
        if not serializer.is_valid():
            logging.error('Malformed outbound data in send_reserve_command() (system bug)')
            logging.error(serializer.errors)
            raise ValidationError('Malformed outbound data (system bug)')
        return ocpi_post(urljoin(f'{route.url}/', 'RESERVE_NOW'), route.token_base64,
                         to=Party(country_code, party_id),
                         sender=get_our_party(OcpiRolesEnum.EMSP),
                         data=serializer.data)
    else:
        message = f"Cannot find a route for RESERVE_NOW to {evse.location.party()}"
        log_error(request, message)
        raise APIException(message)


def send_stop_command(session: Session) -> Optional[Response]:
    country_code = session.location.ocpi_master.country_code
    party_id = session.location.ocpi_master.party_id

    route: Route = find_route(Party(country_code, party_id), OcpiModuleEnum.COMMANDS)
    if route:
        logging.info(f'*** Sending stop command for {session} to {route.url}.')
        authorization_reference = session.authorization_reference
        data = dict(
            response_url=build_absolute_uri(
                reverse('commands-command-result', args=("stop", authorization_reference,))
            ),
            session_id=session.uid
        )
        serializer = StopSessionSerializer(instance=data)
        # ic(serializer.data)
        return ocpi_post(urljoin(f'{route.url}/', 'STOP_SESSION'), route.token_base64,
                         to=Party(country_code, party_id),
                         sender=get_our_party(OcpiRolesEnum.EMSP),
                         data=serializer.data)
    else:
        message = f"Cannot find a route for STOP_SESSION to {country_code}*{party_id}"
        logging.error(message)
        raise APIException(message)
