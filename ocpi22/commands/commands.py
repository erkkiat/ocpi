from icecream import ic

import ocpi22.logging as logging

from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from typing import Union, Optional
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.db import transaction
from django.http import Http404
from django.utils.datetime_safe import datetime
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, APIException, ValidationError
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.viewsets import GenericViewSet

import ocpi22.util
from ocpi22.locations.location import send_to_webhook
from ocpi22.ocpi.serializers import TokenSerializer
from ocpi22.ocpi.auth import OCPIPermission
from ocpi22.choices import EndpointRoleEnum, OcpiModuleEnum, OcpiRolesEnum, MessageTexts
from ocpi22.commands.serializers import StartSessionSerializer, StopSessionSerializer, UnlockConnectorSerializer, \
    CommandResponse, CommandResultSerializer, ReserveNowSerializer
from ocpi22.cpo.serializers import CPOStartWebhookSerializer, CPOStopWebhookSerializer, \
    CPOReserveNowWebhookSerializer
from ocpi22.models.credentials import CredentialsRole, Endpoint
from ocpi22.models.location import Evse, Location, Connector
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.rendering import RENDERERS
from ocpi22.routing import find_route, Route
from ocpi22.sessions.util import create_session
from ocpi22.ocpi.util import ocpi_post, OCPIResponse, Ocpi, generate_auth_reference, options_message
from ocpi22.ocpi.util_party import get_sender_party

from ocpi22.tokens.util import construct_adhoc_token
from ocpiconnector.ocpi_identities import get_our_party, Party
from ocpi22.util import OnlyRawBrowsableAPIRenderer, build_absolute_uri, command_store, \
    build_callback_request
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
    # noinspection PyUnresolvedReferences
    queryset = Session.objects.none()  # Users who can access Sessions can issue Commands also
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
            f' (You need to be using Credentials for the connection.)'
        return billed_to

    error_response = ResponseData(ocpi_status=2000, result=CommandResponse.REJECTED,
                                  http_status=status.HTTP_503_SERVICE_UNAVAILABLE, message=[], timeout=60)

    @transaction.atomic
    @action(methods=['GET', 'POST'], detail=False, url_name='reserve-now', url_path='RESERVE_NOW')
    def reserve_now(self, request):

        # TODO: If this Token is of type RFID, the CPO SHALL NOT do a realtime authorization at the eMSP for
        #  this Token at the given EVSE/Charge Point within 15 minutes after having received this ReserveNow.

        # TODO: The eMSP MAY use Tokens that have not been pushed via the Token module, especially
        #  AD_HOC_USER or APP_USER Tokens are only used by commands send by an eMSP.
        #  As these are never used locally at the Charge Point like RFID.

        result = None
        if not request.data:
            return OCPIResponse({'status_message': options_message}, status=status.HTTP_400_BAD_REQUEST)
        try:
            billed_to = self._get_sender_party(request)
            serializer = ReserveNowSerializer(data=request.data)
            if serializer.is_valid():
                token = serializer.validated_data.get('token', '')
                authorization_reference = serializer.validated_data.get('authorization_reference')

                # Store the command for use during the next {settings.REMOTE_COMMAND_EXPIRATION} seconds
                command_store[authorization_reference] = serializer.validated_data

                params = deepcopy(serializer.validated_data)
                params.update(
                    dict(
                        ad_hoc_token=token,
                        billed_to=str(billed_to),
                        authorization_method=Session.COMMAND,
                        credentials=request.credentials,
                        connector_id=None,
                    )
                )
                for key in ('token', 'response_url', 'expiry_date', 'reservation_id'):
                    params.pop(key)

                session: Session = create_session(**params)
                logging.info(f'Created session {session.uid} based on remote command from MSP')
                # The default scenario, until proven successful
                response: ResponseData = deepcopy(self.error_response)

                try:
                    # Prepare the start command for CPO management system
                    initial_data = deepcopy(serializer.validated_data)
                    initial_data.update(dict(
                        response_url=ocpi22.util.build_absolute_uri(reverse('chargepoint-remote-command-result',
                                                                            args=(session.authorization_reference,))),
                        token_id=session.cdr_token_uid,
                        evse_id=session.evse.uid,
                        token_type=session.cdr_token_type,
                        auth_method=session.auth_method,
                        from_party=str(request.credentials.party()),
                        billed_to=session.billed_to,
                        ocpp_reservation_id=session.ocpp_reservation_id,
                    ))

                    data = send_to_webhook(initial_data, CPOReserveNowWebhookSerializer)

                    response.timeout = data.get('timeout', response.timeout)
                    result = data.get('result', '').upper()
                    logging.info(f'Result from charger for start charging: {result}')
                    response.message = MessageTexts.get(
                        f'RESERVE_{result}',  # Try to get response message for RESERVE_<result>
                        MessageTexts.get(
                            result,  # Then just <result>
                            MessageTexts.get('DEFAULT_CHARGER_ERROR_TEXT')))  # Or just use the default
                    if result:
                        response.ocpi_status = Ocpi.OK
                        response.http_status = status.HTTP_200_OK

                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, ValueError,
                        ValidationError) as e:
                    response.message = MessageTexts.get('MS_CONNECTION_ERROR')
                    response.http_status = status.HTTP_503_SERVICE_UNAVAILABLE
                    logging.error(f'Unable to relay Command to CPO: {e}')

                response_serializer = CommandResponse(
                    instance=dict(result=result, timeout=response.timeout, message=response.message)
                )
                return OCPIResponse(response_serializer.data,
                                    status_code=response.ocpi_status,
                                    http_status=response.http_status)
        except (NotFound, KeyError, Evse.DoesNotExist, Location.DoesNotExist,
                Connector.DoesNotExist, Token.DoesNotExist, AssertionError) as e:
            log_error(request, e)
            return OCPIResponse(None, status_message=f'Unable to make reservation: {e}',
                                http_status=status.HTTP_400_BAD_REQUEST,
                                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)
        return OCPIResponse(serializer.errors, status_message='Please check your request parameters',
                            http_status=status.HTTP_400_BAD_REQUEST,
                            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    @transaction.atomic
    @action(methods=['GET', 'POST'], detail=False, url_name='start-session', url_path='START_SESSION')
    def start_session(self, request):
        if not request.data:
            return OCPIResponse({'status_message': options_message}, status=status.HTTP_400_BAD_REQUEST)
        try:
            billed_to = self._get_sender_party(request)
            serializer = StartSessionSerializer(data=request.data)
            if serializer.is_valid():

                token = serializer.validated_data.get('token', '')
                authorization_reference = serializer.validated_data.get('authorization_reference')

                # Store the command for use during the next {settings.REMOTE_COMMAND_EXPIRATION} seconds
                command_store[authorization_reference] = serializer.validated_data

                # TODO: Do not create Session before making sure the charger is not busy,
                #  it will close active Session(s)

                session: Session = Session.get_if_exists(authorization_reference=authorization_reference)
                if not session:
                    params = serializer.validated_data
                    params.update(
                        dict(
                            ad_hoc_token=token,
                            billed_to=str(billed_to),
                            authorization_method=Session.COMMAND,
                            credentials=request.credentials,
                        )
                    )
                    for key in ('token', 'response_url'):
                        params.pop(key)

                    session: Session = create_session(**params)
                    logging.info(f'Created session {session.uid} based on remote command from MSP')
                else:
                    logging.info(f'Found an existing session {session.uid} based on reservation from MSP')

                # The worst scenario is this
                ocpi_status = 2000
                result = CommandResponse.REJECTED
                http_status = status.HTTP_503_SERVICE_UNAVAILABLE
                message = []
                timeout = 60

                try:
                    # Prepare the start command for CPO management system
                    initial_data = dict(
                        response_url=ocpi22.util.build_absolute_uri(reverse('chargepoint-remote-command-result',
                                                                            args=(session.authorization_reference,))),
                        token_id=session.cdr_token_uid,
                        token_type=session.cdr_token_type,
                        authorization_reference=session.authorization_reference,
                        auth_method=session.auth_method,
                        from_party=str(request.credentials.party()),
                        evse_id=session.evse.uid,
                        connector_id=session.connector.uid if session.connector else None,
                        billed_to=session.billed_to,
                    )

                    data = send_to_webhook(initial_data, CPOStartWebhookSerializer)

                    timeout = int(data.get('timeout', timeout))
                    result = data.get('result', '').upper()
                    logging.info(f'Result from charger for start charging: {result}')
                    message = MessageTexts.get(
                        f'START_{result}',  # Try to get response message for START_<result>
                        MessageTexts.get(
                            result,  # Then just <result>
                            MessageTexts.get('DEFAULT_CHARGER_ERROR_TEXT')))  # Or just use the default
                    if result:
                        ocpi_status = Ocpi.OK
                        http_status = status.HTTP_200_OK

                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, ValueError,
                        ValidationError) as e:
                    message = MessageTexts.get('MS_CONNECTION_ERROR')
                    http_status = status.HTTP_503_SERVICE_UNAVAILABLE
                    logging.error(f'Unable to relay Command to CPO: {e}', request)

                response_serializer = CommandResponse(
                    instance=dict(result=result, timeout=timeout, message=message)
                )
                return OCPIResponse(response_serializer.data, status_code=ocpi_status, http_status=http_status)
        except (NotFound, KeyError, Evse.DoesNotExist, Location.DoesNotExist,
                Connector.DoesNotExist, Token.DoesNotExist, AssertionError) as e:
            log_error(request, e)
            return OCPIResponse(None, status_message=f'Unable to start session: {e}',
                                http_status=status.HTTP_400_BAD_REQUEST,
                                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)
        return OCPIResponse(serializer.errors, status_message='Please check your request parameters',
                            http_status=status.HTTP_400_BAD_REQUEST,
                            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    @transaction.atomic
    @action(methods=['GET', 'POST'], detail=False, url_path='STOP_SESSION')
    def stop_session(self, request):
        if not request.data:
            return OCPIResponse({'status_message': options_message}, status=status.HTTP_400_BAD_REQUEST)
        try:
            serializer = StopSessionSerializer(data=request.data)
            if serializer.is_valid():
                session: Session = Session.get_if_exists(uid=serializer.validated_data.get('session_id'))

                # The worst scenario is this
                ocpi_status = 2000
                result = CommandResponse.REJECTED
                http_status = status.HTTP_503_SERVICE_UNAVAILABLE
                message = []
                timeout = 60

                try:
                    from_party = ''
                    if hasattr(request, 'credentials'):
                        from_party = request.credentials.party()

                    # Prepare the stop command for CPO management system
                    initial_data = dict(
                        response_url=build_absolute_uri(reverse('chargepoint-remote-command-result',
                                                                args=(session.authorization_reference,))),
                        token_id=session.cdr_token_uid,
                        token_type=session.cdr_token_type,
                        authorization_reference=session.authorization_reference,
                        auth_method=session.auth_method,
                        from_party=from_party,
                        evse_id=session.evse.uid,
                        connector_id=session.connector.uid if session.connector else None,
                        billed_to=session.billed_to,
                    )

                    data = send_to_webhook(initial_data, CPOStopWebhookSerializer)

                    timeout = data.get('timeout', timeout)
                    result = data.get('result', '').upper()
                    logging.info(f'Result from charger for stop charging: {result}')
                    message = MessageTexts.get(
                        f'STOP_{result}',  # Try to get STOP_<result>
                        MessageTexts.get(
                            result,  # Then just <result>
                            MessageTexts.get('DEFAULT_CHARGER_ERROR_TEXT')))  # Or finally just get the default
                    if result:
                        ocpi_status = Ocpi.OK
                        http_status = status.HTTP_200_OK

                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, ValueError,
                        ValidationError) as e:
                    message = MessageTexts.get('MS_CONNECTION_ERROR')
                    http_status = status.HTTP_503_SERVICE_UNAVAILABLE
                    logging.error(f'Unable to relay Command to CPO: {e}')

                response_serializer = CommandResponse(
                    instance=dict(result=result, timeout=timeout, message=message)
                )
                return OCPIResponse(response_serializer.data, status_code=ocpi_status, http_status=http_status)
        except (NotFound, KeyError, Evse.DoesNotExist, Location.DoesNotExist,
                Connector.DoesNotExist, Token.DoesNotExist, AssertionError) as e:
            log_error(request, e)
            return OCPIResponse(None, status_message=f'Unable to start session: {e}',
                                http_status=status.HTTP_400_BAD_REQUEST,
                                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)
        return OCPIResponse(serializer.errors, status_message='Please check your request parameters',
                            http_status=status.HTTP_400_BAD_REQUEST,
                            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    @transaction.atomic
    @action(methods=['GET', 'POST'], detail=False, url_path='UNLOCK_CONNECTOR')
    def unlock_connector(self, request):
        if not request.data:
            return OCPIResponse({'status_message': options_message}, status=status.HTTP_400_BAD_REQUEST)
        try:
            serializer = UnlockConnectorSerializer(data=request.data)
            if serializer.is_valid():
                result = 'ACCEPTED'
                # if not CHARGER.unlock_connector(**serializer.data):
                #     return OCPIResponse(status_message=f'Unable to unlock connector at this time',
                #                         http_status=status.HTTP_404_NOT_FOUND,
                #                         status_code=Ocpi.ClientError.UNKNOWN_LOCATION)

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

    @transaction.atomic
    @action(methods=['GET', 'POST'], detail=False, url_path='COMMAND_RESULT/(?P<command>[^/.]+)/(?P<command_id>[^/.]+)')
    def command_result(self, request, command=None, command_id=None):
        """
        This is only used by eMSP for receiving the final result for remote command
        """
        if not request.data:
            return OCPIResponse({'status_message': options_message}, status=status.HTTP_400_BAD_REQUEST)
        try:
            session = Session.objects.filter(authorization_reference=command_id)
            if not session.exists():
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
                return OCPIResponse(
                    status_message='Command result received, thank you!',
                    data=dict(command_id=command_id))
            return OCPIResponse(serializer.errors, status_message='Please check your request parameters',
                                http_status=status.HTTP_400_BAD_REQUEST,
                                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)
        except (NotFound, Http404, KeyError) as e:
            return OCPIResponse(None, status_message=str(e),
                                http_status=status.HTTP_400_BAD_REQUEST,
                                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    @staticmethod
    def list(request, *_args, **_kwargs):
        return Response(dict(
            start_session=request.build_absolute_uri(reverse('commands-start-session')),
            stop_session=request.build_absolute_uri(reverse('commands-stop-session')),
            unlock_connector=request.build_absolute_uri(reverse('commands-unlock-connector')),
            reserve_now=request.build_absolute_uri(reverse('commands-reserve-now')),
            # command_result=request.build_absolute_uri(reverse('commands-command-result')),
        ))


def get_our_first_token():
    our_country_code, our_party_id = Token.get_owner_identity().split('*')

    try:
        return Token.objects.filter(country_code=our_country_code, party_id=our_party_id)[0]
    except IndexError:
        raise ValueError('Please create a Token first.')


def find_endpoint(country_code, party_id, identifier: OcpiModuleEnum, endpoint_role: EndpointRoleEnum) -> Endpoint:
    # noinspection PyUnresolvedReferences
    for role in CredentialsRole.objects.filter(country_code=country_code, party_id=party_id):
        for credentials in role.credentials.all():
            # noinspection PyUnresolvedReferences
            endpoints = credentials.endpoints.filter(identifier=identifier.value, role=endpoint_role.value)
            if endpoints.count():
                return endpoints[0]


def send_start_command(request, evse: Evse, token: Union[Token, str], connector_id=None, contract_id='') -> Response:
    """
    As an eMSP we send an OCPI Command START_SESSION to the CPO
    """
    country_code = evse.location.country_code
    party_id = evse.location.party_id

    route: Route = find_route(Party(country_code, party_id), OcpiModuleEnum.COMMANDS)
    if route:
        logging.info(f'*** Sending start command for {evse.location.name} to {route.url}.')
        if not isinstance(token, Token):
            token = construct_adhoc_token(token, contract_id=contract_id)
        token_data = TokenSerializer(token).data
        authorization_reference = generate_auth_reference()
        data = dict(
            response_url=build_absolute_uri(
                reverse('commands-command-result', args=("start", authorization_reference,))
            ),
            token=token_data,
            location_id=evse.location.uid,
            evse_uid=evse.uid,
            connector_id=connector_id,
            authorization_reference=authorization_reference,  # Todo: Store authorization for verifying CDR
        )
        serializer = StartSessionSerializer(instance=data)
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
    country_code = evse.location.country_code
    party_id = evse.location.party_id

    route: Route = find_route(Party(country_code, party_id), OcpiModuleEnum.COMMANDS)
    if route:
        logging.info(f'*** Sending reserve command for {evse.location.name} to {route.url}.')
        if not isinstance(token, Token):
            token = construct_adhoc_token(token, contract_id=contract_id)
        token_data = TokenSerializer(token).data
        authorization_reference = generate_auth_reference()
        if evse.location != location:
            raise ValidationError(f'The EVSE {evse.evse_id} is not at location {location.uid}')
        data = dict(
            response_url=build_absolute_uri(
                reverse('commands-command-result', args=("reserve", authorization_reference,))
            ),
            token=token_data,
            location_id=location.uid,
            evse_uid=evse.uid,
            connector_id=connector_id,
            authorization_reference=authorization_reference,  # Todo: Store authorization for verifying CDR
            expiry_date=datetime.now() + timedelta(seconds=expiration),
            reservation_id=reservation_id
        )
        serializer = ReserveNowSerializer(data=data)
        if not serializer.is_valid():
            logging.error('Malformed outbound data in send_reserve_command() (OCPI Connector bug)')
            logging.error(serializer.errors)
            raise ValidationError('Malformed outbound data (OCPI Connector bug)')
        return ocpi_post(urljoin(f'{route.url}/', 'RESERVE_NOW'), route.token_base64,
                         to=Party(country_code, party_id),
                         sender=get_our_party(OcpiRolesEnum.EMSP),
                         data=serializer.data)
    else:
        message = f"Cannot find a route for RESERVE_NOW to {evse.location.party()}"
        log_error(request, message)
        raise APIException(message)


def send_stop_command(session: Session) -> Optional[Response]:
    if session.status != session.ACTIVE:
        raise ValidationError(f'Session {session.uid} is not active and cannot be stopped')

    country_code = session.location.country_code
    party_id = session.location.party_id

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
