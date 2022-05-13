import logging
from json import JSONDecodeError
from typing import Union, Optional
from urllib.parse import urljoin

import requests
from django.db import transaction
from django.http import Http404
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, APIException
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.viewsets import GenericViewSet

import ocpi22.util
from ocpi22.ocpi.serializers import TokenSerializer
from ocpi22.ocpi.auth import OCPIPermission
from ocpi22.choices import EndpointRoleEnum, OcpiModuleEnum, OcpiRolesEnum, MessageTexts
from ocpi22.commands.serializers import StartSessionSerializer, StopSessionSerializer, UnlockConnectorSerializer, \
    CommandResponse, CommandResultSerializer
from ocpi22.cpo.api import CHARGER
from ocpi22.cpo.util import get_callbacks_parameter, command_store
from ocpi22.cpo.serializers import CallbacksSerializer
from ocpi22.models.credentials import CredentialsRole, Endpoint
from ocpi22.models.location import Evse, Location, Connector
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.routing import find_route, Route
from ocpi22.sessions.util import create_session
from ocpi22.ocpi.util import ocpi_post, OCPIResponse, Ocpi, get_sender_party, generate_auth_reference

import pprint

from ocpi22.tokens.util import construct_adhoc_token
from ocpiconnector.ocpi_identities import get_our_party, Party
from ocpi22.util import OnlyRawBrowsableAPIRenderer, ParseUrl, build_absolute_uri
from ocpi22.logging import log_error

pp = pprint.PrettyPrinter(indent=4).pprint


class CommandsViewSet(GenericViewSet):
    # root_view_name = 'commands'
    # noinspection PyUnresolvedReferences
    queryset = Session.objects.none()  # Users who can access Sessions can issue Commands also
    permission_classes = [OCPIPermission]
    renderer_classes = [JSONRenderer, OnlyRawBrowsableAPIRenderer]

    def get_serializer_class(self):
        if not hasattr(self, 'action_map'):
            return serializers.Serializer
        # ic(self.action_map['post'])
        serializer = dict(
            start_session=StartSessionSerializer,
            stop_session=StopSessionSerializer,
            unlock_connector=UnlockConnectorSerializer,
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
    def _format_url(url, **kwargs) -> str:
        """
        >>> c = CommandsViewSet()
        >>> c._format_url("https://fakehost/start/{evse_id}/", evse_id=1)
        'https://fakehost/start/1/'
        """
        if isinstance(url, bytes):
            url = url.decode("utf-8")
        return url.format(**kwargs)

    @transaction.atomic
    @action(methods=['GET', 'POST'], detail=False, url_name='start-session', url_path='START_SESSION')
    def start_session(self, request):
        if not request.data:
            return OCPIResponse(status_message='Please see OPTIONS to learn what you can POST at this endpoint')
        try:
            billed_to = get_sender_party(request.META)
            assert isinstance(billed_to, Party) and len(str(billed_to)) == 6, \
                f'Billed_to needs to be set with party ID: {billed_to}'
            serializer = StartSessionSerializer(data=request.data)
            if serializer.is_valid():

                token = serializer.validated_data.get('token', '')
                authorization_reference = serializer.validated_data.get('authorization_reference')

                # Store the command for use during the next {settings.REMOTE_COMMAND_EXPIRATION} seconds
                command_store[authorization_reference] = serializer.validated_data

                params = serializer.validated_data
                params.update(
                    dict(
                        ad_hoc_token=token,
                        billed_to=str(billed_to),
                        authorize_from_msp=False,
                    )
                )
                params.pop('token')
                params.pop('response_url')

                session: Session = create_session(send_updates=False, **params)

                # The worst scenario is this
                ocpi_status = 2000
                result = CommandResponse.REJECTED
                http_status = status.HTTP_503_SERVICE_UNAVAILABLE
                message = []
                timeout = 60

                try:
                    # Prepare the start command for CPO management system
                    data = dict(
                        response_url=ocpi22.util.build_absolute_uri(reverse('chargepoint-remote-command-result',
                                                                            args=(session.authorization_reference,))),
                        token_id=session.cdr_token_uid,
                        token_type=session.cdr_token_type,
                        authorization_reference=session.authorization_reference,
                        auth_method=session.auth_method,
                        billed_to=session.billed_to,
                        evse_id=session.evse.uid,
                        connector_id=session.connector.uid if session.connector else None,
                    )

                    # ic(data)
                    # Use basic auth if required
                    kwargs = dict()
                    headers = {'content-type': 'application/json'}
                    url = get_callbacks_parameter(CallbacksSerializer.START_TRANSACTION_URL)
                    parsed = ParseUrl(url)
                    user = parsed.username
                    password = parsed.password
                    if user and password:
                        kwargs.update(dict(auth=(user, password)))

                    url = self._format_url(parsed.url, user=user, evse_id=session.evse.uid)

                    # ic(url, data, kwargs)
                    # Send start command to CPO
                    logging.info(f'Sending CPO command to url {url}')
                    cpo_response = requests.post(
                        url=url,
                        json=data,
                        headers=headers,
                        verify=False,
                        **kwargs)
                    data = cpo_response.json()

                    if data:
                        timeout = data.get('timeout', timeout)
                        result = data.get('result')
                        # ic(result)
                        if result:
                            message = MessageTexts.get(f'START_{result.upper()}',
                                                       MessageTexts.DEFAULT_CHARGER_ERROR_TEXT)
                            ocpi_status = 1000
                            http_status = status.HTTP_200_OK
                        else:
                            result = 'REJECTED'
                except (requests.exceptions.ConnectionError, JSONDecodeError) as e:
                    message = MessageTexts.MS_CONNECTION_ERROR
                    http_status = status.HTTP_424_FAILED_DEPENDENCY
                    logging.error(f'Unable to relay Command to CPO: {e}')

                response_serializer = CommandResponse(
                    instance=dict(result=result, timeout=timeout, message=message)
                )
                return OCPIResponse(response_serializer.data, status_code=ocpi_status, http_status=http_status)
        except (NotFound, KeyError, Evse.DoesNotExist, Location.DoesNotExist,
                Connector.DoesNotExist, Token.DoesNotExist,) as e:
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
            return OCPIResponse(status_message='Please see OPTIONS to learn what you can POST at this endpoint')
        try:
            serializer = StopSessionSerializer(data=request.data)
            if serializer.is_valid():
                session: Session = Session.get_if_exists(uid=serializer.validated_data.get('session_id'))
                session.status = Session.COMPLETED
                session.save()

                # The worst scenario is this
                ocpi_status = 2000
                result = CommandResponse.REJECTED
                http_status = status.HTTP_503_SERVICE_UNAVAILABLE
                message = []
                timeout = 60

                try:
                    # Prepare the stop command for CPO management system
                    data = dict(
                        response_url=request.build_absolute_uri(reverse('chargepoint-remote-command-result',
                                                                        args=(session.authorization_reference,))),
                        token_id=session.cdr_token_uid,
                        token_type=session.cdr_token_type,
                        authorization_reference=session.authorization_reference,
                        auth_method=session.auth_method,
                        billed_to=session.billed_to,
                        evse_id=session.evse.uid,
                        connector_id=session.connector.uid if session.connector else None,
                    )

                    # ic(data)
                    # Use basic auth if required
                    kwargs = dict()
                    headers = {'content-type': 'application/json'}
                    url = get_callbacks_parameter(CallbacksSerializer.STOP_TRANSACTION_URL)
                    parsed = ParseUrl(url)
                    user = parsed.username
                    password = parsed.password
                    if user and password:
                        kwargs.update(dict(auth=(user, password)))

                    url = self._format_url(parsed.url, user=user, evse_id=session.evse.uid)

                    # ic(url, data, kwargs)
                    # Send start command to CPO
                    logging.info(f'Sending CPO command to url {url}')
                    cpo_response = requests.post(
                        url=url,
                        json=data,
                        headers=headers,
                        verify=False,
                        **kwargs)
                    data = cpo_response.json()

                    if data:
                        timeout = data.get('timeout', timeout)
                        result = data.get('result')
                        # ic(result)
                        if result:
                            message = MessageTexts.get(f'STOP_{result.upper()}',
                                                       MessageTexts.DEFAULT_CHARGER_ERROR_TEXT)
                            ocpi_status = 1000
                            http_status = status.HTTP_200_OK
                        else:
                            result = 'REJECTED'
                except (requests.exceptions.ConnectionError, JSONDecodeError) as e:
                    message = MessageTexts.MS_CONNECTION_ERROR
                    http_status = status.HTTP_424_FAILED_DEPENDENCY
                    logging.error(f'Unable to relay Command to CPO: {e}')

                response_serializer = CommandResponse(
                    instance=dict(result=result, timeout=timeout, message=message)
                )
                return OCPIResponse(response_serializer.data, status_code=ocpi_status, http_status=http_status)
        except (NotFound, KeyError, Evse.DoesNotExist, Location.DoesNotExist,
                Connector.DoesNotExist, Token.DoesNotExist,) as e:
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

    @transaction.atomic
    @action(methods=['GET', 'POST'], detail=False, url_path='COMMAND_RESULT/(?P<command>[^/.]+)/(?P<command_id>[^/.]+)')
    def command_result(self, request, command=None, command_id=None):
        """
        This is only used by eMSP for receiving the final result for remote command
        """
        if not request.data:
            return OCPIResponse(status_message='Please see OPTIONS to learn what you can POST at this endpoint')
        try:
            serializer = CommandResultSerializer(data=request.data)
            if serializer.is_valid():
                result = serializer.validated_data.get('result')
                logging.info(f'Received CommandResult {result} for command {command} ID {command_id}')
                return OCPIResponse(
                    status_message='Command result received, thank you!',
                    data=dict(command_id=command_id))
        except (NotFound, Http404, KeyError) as e:
            return OCPIResponse(None, status_message=str(e),
                                http_status=status.HTTP_400_BAD_REQUEST,
                                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)
        return OCPIResponse(serializer.errors, status_message='Please check your request parameters',
                            http_status=status.HTTP_400_BAD_REQUEST,
                            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    @staticmethod
    def list(request, *_args, **_kwargs):
        return Response(dict(
            start_session=request.build_absolute_uri(reverse('commands-start-session')),
            stop_session=request.build_absolute_uri(reverse('commands-stop-session')),
            unlock_connector=request.build_absolute_uri(reverse('commands-unlock-connector')),
            # command_result=request.build_absolute_uri(reverse('commands-command-result')),
        ))


def get_our_first_token():
    our_country_code, our_party_id = Token.get_owner_identity().split('*')

    try:
        # noinspection PyUnresolvedReferences
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
            response_url=request.build_absolute_uri(
                reverse('commands-command-result', args=("start", authorization_reference,))
            ),
            token=token_data,
            location_id=evse.location.uid,
            evse_uid=evse.uid,
            connector_id=connector_id,
            authorization_reference=authorization_reference,  # Todo: Store authorization for verifying CDR
        )
        serializer = StartSessionSerializer(instance=data)
        # ic(serializer.data)
        return ocpi_post(urljoin(f'{route.url}/', 'START_SESSION'), route.token_base64,
                         to=Party(country_code, party_id),
                         sender=get_our_party(OcpiRolesEnum.EMSP),
                         data=serializer.data)
    else:
        message = f"Cannot find a route for START_SESSION to {evse.location.party()}"
        log_error(request, message)
        raise APIException(message)


def send_stop_command(session: Session) -> Optional[Response]:
    if session.status != session.ACTIVE:
        return None

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
