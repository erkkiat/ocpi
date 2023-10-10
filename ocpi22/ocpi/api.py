from urllib.parse import urljoin

from django.conf import settings
from django.db.models import ProtectedError

import ocpi22.logging as logging
from typing import Optional

from django.core.handlers.wsgi import WSGIRequest
from django.views.decorators.csrf import csrf_exempt
from icecream import ic
from rest_framework import routers, status, mixins
from rest_framework.generics import get_object_or_404
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response

from certification.decorators import certification_step
from ocpi22.decorators import requires_sender_role, requires_credentialsrole, requires_last_updated
from ocpi22.ocpi.partners import get_partners
from ocpi22.routing import find_route
from ocpi22.tasks import send_ocpi_request
from ocpiconnector.exception_handler import ocpi_exception_handler
from util import reverse
from rest_framework.viewsets import GenericViewSet

from ocpi22.choices import MessageTexts, get_language, AuthorizationEnum, OcpiModuleEnum, OcpiRolesEnum
from ocpi22.commands.commands import send_stop_command
from ocpi22.msp.models import Authorization
from ocpi22.webhooks import send_to_webhook
from ocpi22.logging import log_error
from ocpi22.msp.account import update_balance
from ocpi22.msp.serializers import MSPAuthorizeCallbackSerializer, MSPSessionCallbackSerializer
from ocpi22.msp.twilio import message_user
from ocpi22.ocpi.serializers import TokenSerializer, TariffSerializer, CdrSerializer, \
    CredentialsSerializer, SessionSerializer, ClientInfoSerializer, AuthorizeSerializer
from ocpi22.models.credentials import Credentials, CredentialsRole, store_endpoints_for_party
from ocpi22.models.location import Location
from ocpi22.models.tariff import Tariff
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.models.cdr import Cdr
from ocpi22.rendering import RENDERERS
from ocpi22.util import OnlyRawBrowsableAPIRenderer, OCPIVersioning, \
    OCPIListModelMixin, generate_random_token, build_absolute_uri
from ocpi22.ocpi.util import OCPIBadRequestResponse, NotOwner, OCPIResponse, Ocpi, OCPIPaginationAndHeaders, \
    generate_auth_reference, OCPIResponseUrlParametersRequired
from ocpi22.credentials.versions import get_endpoints_dict
from ocpiconnector.management.commands.exchange_credentials import get_our_roles, select_version, get_endpoints
from ocpiconnector.ocpi_identities import ocpi_platform, Party, get_our_party
from premium import requires_premium


# Todo: In case a PATCH request fails, the client is expected to call the GET method to check the state
#  of the object in the other party’s system. If the object doesn’t exist, the client should do a PUT.

# Todo: Only requests/responses from Function Modules: such as: Tokens, Locations, CDRs etc. SHALL be routed,
#  so need the routing headers.


class TokenViewSet(OCPIListModelMixin,
                   GenericViewSet):
    queryset = Token.objects.all().order_by('created')
    serializer_class = TokenSerializer
    pagination_class = OCPIPaginationAndHeaders
    versioning_class = OCPIVersioning
    lookup_field = 'uid'
    renderer_classes = RENDERERS

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'Token {self.kwargs.get("uid")}'
        if self.name:
            return f'{self.name.capitalize()}'
        return f'Tokens'

    @ocpi_exception_handler
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @staticmethod
    def get_object(uid=None) -> Optional[Token]:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Token, uid=uid)

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.EMSP)
    @certification_step(OcpiModuleEnum.TOKENS, 'PUT an individual Token',
                        subtopic='')
    def put(self, request, country_code=None, party_id=None, uid=None, data=None, patch=False, version='2.2.1',
            logentry=None, **_kwargs):
        uid = uid or data.get('uid')

        if not request.party_specified_in_url:
            return OCPIResponseUrlParametersRequired('token')

        token: Token = Token.get_if_exists(uid__iexact=uid, ocpi_master=request.credentialsrole)
        created = bool(not token)
        serializer = TokenSerializer(data=data, instance=token, partial=patch,
                                     context={'version': version or request.version})
        if serializer.is_valid():
            logging.info(
                f'{"Creating" if created else "Updating"} Token {country_code}*{party_id} - {uid}.',
                log_to_admin=True, logentry=logentry
            )
            created_token = serializer.save(ocpi_master=request.credentialsrole)
            created_token.send_hub_updates()
            return OCPIResponse(serializer.data,
                                http_status=status.HTTP_201_CREATED
                                if created else status.HTTP_200_OK)
        return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST)

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.EMSP)
    @requires_last_updated
    @certification_step(OcpiModuleEnum.TOKENS, 'PATCH a Token',
                        subtopic='')
    def patch(self, *args, **kwargs):
        return self.put(*args, patch=True, **kwargs)

    @ocpi_exception_handler
    @csrf_exempt
    @certification_step(OcpiModuleEnum.TOKENS, 'Authorize a Token',
                        subtopic='')
    def authorize(self, request: Request, token_uid, **_kwargs) -> OCPIResponse:
        allowed = AuthorizationEnum.ALLOWED
        ocpi_status = Ocpi.OK
        http_status = 200
        info = None
        status_message = 'Success'
        user_language = 'en'
        max_price = None
        location = None

        try:
            token: Token = Token.get_if_exists(uid=token_uid)
            if not token:
                # OCPI 2.2: If the token is not known, the response SHALL contain the status code:
                # 2004: Unknown Token, and no data field.
                return OCPIResponse(status_code=Ocpi.ClientError.UNKNOWN_TOKEN,
                                    status=status.HTTP_404_NOT_FOUND,
                                    status_message='Unknown Token')
            if request.data:
                serializer = AuthorizeSerializer(data=request.data)
                # ic(token, request.data, serializer.initial_data)
                if serializer.is_valid():
                    location: Location = serializer.validated_data.get('location')
                else:
                    return OCPIBadRequestResponse(data=serializer.errors)

            if token.language:
                user_language = token.language.lower()

            if not token.valid:
                allowed = AuthorizationEnum.EXPIRED
                info = MessageTexts.get('TOKEN_NOT_VALID')
                ocpi_status = 2000
                http_status = status.HTTP_401_UNAUTHORIZED
                status_message = 'Your charging token is not valid at the moment'
                message_user(status_message, '+358405480238')

            # Todo: Update tests for internal accounting and create tests for MSP authorize callback
            webhook_data = {'token_id': token_uid, 'location_id': location.uid if location else None}
            msp_response = send_to_webhook(
                webhook_data,
                MSPAuthorizeCallbackSerializer,
                timeout=28)  # Just under the 30 second limit which is maximum for Heroku requests
            if msp_response:
                serializer = MSPAuthorizeCallbackSerializer.ResponseSerializer(data=msp_response)
                if serializer.is_valid():
                    allowed = msp_response.get('result', 'NOT_ALLOWED').upper()
                    max_price = msp_response.get('max_price')
                else:
                    allowed = 'NOT_ALLOWED'
                http_status = dict(
                    ALLOWED=status.HTTP_200_OK
                ).get(allowed, status.HTTP_401_UNAUTHORIZED)
                ocpi_status = dict(
                    ALLOWED=Ocpi.OK,
                ).get(allowed, Ocpi.ServerError.GENERIC_SERVER_ERROR)
            else:
                if settings.REQUIRE_WALLET_BALANCE and token.total_balance_float() < 1.0:
                    log_error(request, f'Token {token} has no balance')
                    allowed = AuthorizationEnum.NO_CREDIT
                    info = MessageTexts.get('NO_BALANCE')
                    ocpi_status = Ocpi.ClientError.GENERIC_CLIENT_ERROR
                    http_status = status.HTTP_401_UNAUTHORIZED
                    status_message = get_language(user_language, info)
                    # message_user(status_message, '+358405480238')

            # if allowed == AuthorizationEnum.ALLOWED:
            #     message = UserMessages.approve_charging.get(user_language)
            #     ic(message)
            #     message_user(message, '+358405480238', location=location_name,
            #                  price=prices, url="http://secureautocharge.com/132244/")

            serializer = TokenSerializer(instance=token, context={'version': request.version})
            authorization_reference = generate_auth_reference() if allowed == AuthorizationEnum.ALLOWED else ''
            if authorization_reference:
                # Todo: Figure out the balance for the token's owner and set the max_price accordingly
                Authorization.objects.create(authorization_reference=authorization_reference, max_price=max_price)
                logging.info(f'Created authorization reference {authorization_reference} with max price {max_price}')
            return OCPIResponse(
                dict(
                    allowed=allowed,
                    token=serializer.data,
                    authorization_reference=authorization_reference,
                ), status_code=ocpi_status, status=http_status, status_message=status_message
            )
        except ValueError as e:
            return OCPIResponse(
                {},
                status_code=Ocpi.ServerError.GENERIC_SERVER_ERROR,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
                status_message=f'{get_language(user_language, info)}: {str(e)}'
            )

    @ocpi_exception_handler
    @requires_credentialsrole
    @certification_step(OcpiModuleEnum.TOKENS, 'GET an individual Token',
                        subtopic='')
    def get(self, request, credentialsrole, uid=None, **_kwargs):
        """Respond to a GET which has parameters"""

        # Todo: Show only tokens that are relevant to the party
        # Todo: if running as HUB, filter results based on agreed parties
        token = Token.objects.get(ocpi_master=credentialsrole, uid=uid)
        serializer = TokenSerializer(token, many=False, context={'request': request, 'version': request.version})
        return OCPIResponse(serializer.data)


class CdrViewSet(OCPIListModelMixin,
                 GenericViewSet):
    """
    These are the records created for the purpose of billing.
    Once a CDR is created, it must not be modified or removed.
    A CDR can be credited to the customer by creating a credit
    CDR in the admin tools.
    **VISIBILITY**: A CDR record is only available to relevant parties,
    so fetching another party's CDR should not be allowed.
    (When logged in as a superuser, you can see all CDRs)
    """
    # queryset = Cdr.objects.none()  # Default to no visibility, fine tune with get_queryset()
    serializer_class = CdrSerializer
    versioning_class = OCPIVersioning
    pagination_class = OCPIPaginationAndHeaders
    renderer_classes = RENDERERS

    def get_queryset(self):
        if self.request.user.is_superuser:
            return Cdr.objects.all().order_by('created')
        if hasattr(self.request, 'country_code'):
            ic(self.request.country_code, self.request.party_id)
            return Cdr.objects.filter(ocpi_master=self.request.credentialsrole).order_by('created')
        return Cdr.objects.none()

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'CDR {self.kwargs.get("uid")}'
        if self.name:
            return f'CDR {self.name.lower()}'
        return f'Charge Detail Records'

    @staticmethod
    def get_object(uid=None) -> None:
        # Needed for OPTIONS to work in list view
        return None

    @ocpi_exception_handler
    @requires_premium
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @ocpi_exception_handler
    @requires_premium
    @certification_step(OcpiModuleEnum.CDRS, 'GET a CDR which belongs to you',
                        subtopic='URL parameters are required by OCPI 2.2')
    def get(self, request, country_code=None, party_id=None, uid=None, **_kwargs) -> Response:
        cdr = Cdr.objects.get(country_code=country_code, party_id=party_id, uid=uid)
        serializer = CdrSerializer(cdr, many=False, context={'request': request, 'version': request.version})
        return OCPIResponse(serializer.data)

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.CPO)
    @requires_premium
    @certification_step(OcpiModuleEnum.CDRS, 'POST a new CDR',
                        subtopic='')
    def post(self, request, data, **_kwargs) -> OCPIResponse:
        serializer = CdrSerializer(data=data, context={'version': request.version})
        if serializer.is_valid():
            cdr = serializer.save(ocpi_master=request.credentialsrole)
            # cdr.tariffs.set(tariff_list)
            cdr.send_hub_updates()
            if ocpi_platform.is_emsp:
                update_balance(cdr)
                # capture_reservation(cdr)
            url = build_absolute_uri(cdr.get_absolute_url())
            return OCPIResponse(serializer.data, headers=dict(Location=url), http_status=status.HTTP_201_CREATED)
        return OCPIResponse(errors=serializer.errors)


def make_my_credentials_dict(request, our_token) -> dict:
    return dict(
        token=our_token,
        url=build_absolute_uri(reverse('base-versions')),

        # Todo: Check this, should be "Retrieves the credentials object to access the server’s platform"
        roles=get_our_roles(),
    )


class CredentialsViewSet(mixins.ListModelMixin, GenericViewSet):
    """
    Credential tokens exchange. Please note that the tokens are base64 encoded for transport, except in the
    credentials exchange module. For testing purposes, you can include the token by using
    ?auth-test=TOKEN.
    """
    # The queryset tells Django REST how to determine access to these endpoints
    queryset = Credentials.objects.none()
    serializer_class = CredentialsSerializer
    renderer_classes = [OnlyRawBrowsableAPIRenderer, JSONRenderer]

    def get_view_name(self):
        return 'Credentials'

    @ocpi_exception_handler
    @requires_premium
    def list(self, request, *_args, **_kwargs):
        if not hasattr(request, 'credentials'):
            return OCPIResponse("There seem to be no credentials in use for this request.",
                                http_status=status.HTTP_405_METHOD_NOT_ALLOWED,
                                status_code=Ocpi.ClientError.UNKNOWN_TOKEN)
        return OCPIResponse(make_my_credentials_dict(request, request.credentials.ours))

    @ocpi_exception_handler
    @requires_premium
    def delete(self, request: Request, *_args, **_kwargs):
        # Todo: Make sure deletition is not possible for others than owner
        if not hasattr(request, 'credentials'):
            return OCPIResponse("There seem to be no credentials in use for this request.",
                                http_status=status.HTTP_405_METHOD_NOT_ALLOWED,
                                status_code=Ocpi.ClientError.UNKNOWN_TOKEN)
        logging.warning(f'Soft deleting {request.credentials} on request by Credential owner (valid=False).')
        request.credentials.soft_delete()
        return OCPIResponse(status_message='Your credentials have been deleted, as requested.')

    @ocpi_exception_handler
    @requires_premium
    @csrf_exempt
    def post(self, request: Request, *_args, **_kwargs):
        credentials: Credentials = getattr(request, 'credentials', None)
        assert credentials, f'Posting to this endpoint requires OCPI Credentials'
        assert not credentials.theirs, \
            f'Credentials exist already, use PUT to update'
        data = request.data.get('data', request.data)
        credentials.theirs = data.get('token')
        credentials.url = data.get('url')
        if not credentials.ours:
            credentials.ours = generate_random_token()
        try:
            credentials.roles.all().delete()
            for role in data['roles']:
                credentials.add_role(role)
        except ProtectedError as e:
            # If CredentialsRoles are in use, we cannot touch them in any way, so skipping the delete and add_role
            logging.error(f'Unable to delete CredentialsRoles: {e}')

        # Delay storing tokens until now, in case the roles have some issue
        credentials.save()

        token_base64 = credentials.theirs_base64()  # CREDENTIALS_TOKEN_B
        versions_url = select_version(credentials.url, token_base64)
        endpoints = get_endpoints(versions_url, token_base64)
        store_endpoints_for_party(credentials, endpoints)
        data = make_my_credentials_dict(request, our_token=credentials.ours)
        serializer = CredentialsSerializer(data=data, context={'version': request.version})
        if not serializer.is_valid():
            logging.error(f'Our software has a logic error in Credentials POST: {serializer.errors}')
            return OCPIResponse(
                dict(
                    status_text='Sorry, but we have a slight problem. Support has been alerted.'
                ),
                status_code=Ocpi.ServerError.GENERIC_SERVER_ERROR,
                status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return OCPIResponse(data, http_status=status.HTTP_201_CREATED)

    @ocpi_exception_handler
    @requires_premium
    @csrf_exempt
    def put(self, request: Request, *_args, **_kwargs):
        credentials: Credentials = getattr(request, 'credentials', None)
        assert credentials, f'Posting to this endpoint requires OCPI Credentials'
        assert credentials.theirs and credentials.ours, \
            f'Credentials registration has not been finalized, please use POST first'
        data = request.data
        data = data.get('data', data)
        credentials.theirs = data.get('token')
        credentials.url = data.get('url')
        # *Do not allow updating the CredentialsRoles, it is a security vulnerability*
        credentials.save()

        token_base64 = credentials.theirs_base64()  # CREDENTIALS_TOKEN_B
        versions_url = select_version(credentials.url, token_base64)
        endpoints = get_endpoints(versions_url, token_base64)
        store_endpoints_for_party(credentials, endpoints)
        data = make_my_credentials_dict(request, our_token=credentials.ours)
        serializer = CredentialsSerializer(data=data, context={'version': request.version})
        if not serializer.is_valid():
            logging.error(f'Our software has a logic error in Credentials POST: {serializer.errors}')
            return OCPIResponse(
                dict(
                    status_text='Sorry, but we have a slight problem. Support has been alerted.'
                ),
                status_code=Ocpi.ServerError.GENERIC_SERVER_ERROR,
                status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return OCPIResponse(data)


class TariffViewSet(OCPIListModelMixin,
                    GenericViewSet):
    queryset = Tariff.objects.exclude(archived=True).order_by('created')
    serializer_class = TariffSerializer
    versioning_class = OCPIVersioning
    pagination_class = OCPIPaginationAndHeaders
    lookup_field = 'uid'
    renderer_classes = RENDERERS

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'Tariff {self.kwargs.get("uid")}'
        if self.name:
            return f'{self.name.capitalize()}'
        return 'Tariffs'

    @ocpi_exception_handler
    @requires_premium
    def list(self, *args, **kwargs):
        return super().list(*args, **kwargs)

    @ocpi_exception_handler
    @requires_premium
    @requires_credentialsrole
    def get(self, request: Request, credentialsrole, uid, *_args, **_kwargs):
        """Handle a GET request for a specific Tariff"""
        tariff = Tariff.objects.get(ocpi_master=credentialsrole, uid__iexact=uid, archived=False)
        serializer = self.get_serializer(tariff, many=False,
                                         context={'request': request, 'version': request.version})
        return OCPIResponse(serializer.data)

    @staticmethod
    def get_object(uid=None) -> Tariff:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Tariff, uid=uid)

    @ocpi_exception_handler
    @requires_premium
    @requires_sender_role([OcpiRolesEnum.CPO, OcpiRolesEnum.HUB])
    @requires_credentialsrole
    @certification_step(OcpiModuleEnum.TARIFFS, 'PUT an individual Tariff',
                        subtopic='URL parameters are required by OCPI 2.2')
    def put(self, request, credentialsrole, uid=None, data=None, version='2.2.1',
            logentry=None, **_kwargs) \
            -> OCPIResponse:
        uid = uid or data.get('id')

        if not request.party_specified_in_url:
            return OCPIResponseUrlParametersRequired('tariff')

        tariff: Tariff = Tariff.get_if_exists(uid__iexact=uid, ocpi_master=credentialsrole, archived=False)
        created = bool(not tariff)
        if tariff and tariff.is_ours():
            return OCPIResponse(f'Tariff {tariff} is owned by us and cannot be updated from outside.',
                                http_status=status.HTTP_401_UNAUTHORIZED,
                                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)
        serializer = TariffSerializer(instance=tariff, data=data, context={'version': version or request.version,
                                                                           'request': request})
        if serializer.is_valid():
            logging.info(f'{"Creating" if created else "Updating"} Tariff {credentialsrole} - {uid}.',
                         logentry=logentry, log_to_admin=True)
            created_tariff = serializer.save(ocpi_master=credentialsrole)
            created_tariff.send_hub_updates()
            return OCPIResponse(serializer.data, http_status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
        else:
            return OCPIResponse(errors=serializer.errors)

    @ocpi_exception_handler
    @requires_sender_role([OcpiRolesEnum.CPO, OcpiRolesEnum.HUB])
    @requires_premium
    @requires_credentialsrole
    @certification_step(OcpiModuleEnum.TARIFFS, 'DELETE an individual Tariff',
                        subtopic='')
    def delete(self, request, credentialsrole, uid, *_args, **_kwargs) -> OCPIResponse:
        """Process a DELETE rest call for a Tariff"""
        tariff = Tariff.objects.get(uid__iexact=uid, ocpi_master=credentialsrole, archived=False)
        if tariff.ocpi_master != request.credentialsrole \
                and not request.user.is_superuser \
                and request.credentials and not request.credentials.is_hub:
            return NotOwner(f'Only the owner or a HUB can delete the tariff {uid}.')
        if not tariff:
            return OCPIResponse(f'No Tariff found with {request.credentialsrole} and uid={uid}.',
                                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)
        if hasattr(tariff, 'connectors') and tariff.connectors and tariff.connectors.count():
            return OCPIResponse('Cannot delete a Tariff which is referred to by one or more Connectors.',
                                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)
        tariff.delete()
        return OCPIResponse('Tariff was deleted')


def stop_session_if_money_runs_out(request, session):
    if hasattr(session, 'authorization'):
        authorization = session.authorization
        if authorization:
            reserved_money = authorization.max_price
            if reserved_money is not None and session.total_cost_incl_vat is not None \
                    and float(reserved_money) - session.total_cost_incl_vat < 2.0:
                response = send_stop_command(session)
                if response.status_code != status.HTTP_200_OK:
                    logging.error(
                        f'Unable to stop Session {session.uid} before the reserved money {reserved_money} runs out',
                        request)


def fetch_location(country_code, party_id, location_id, evse_uid) -> bool:
    party = Party(country_code, party_id)
    route = find_route(to=party, ocpi_module=OcpiModuleEnum.LOCATIONS)
    if not route:
        return None
    url = urljoin(route.url, f'{country_code}/{party_id}/{location_id}')
    we = get_our_party(OcpiRolesEnum.EMSP) or get_our_party(OcpiRolesEnum.HUB)
    print(f'Fetching unknown location from {party=}, {route=}, {url=}, {we=}')
    response = send_ocpi_request(data=dict(), url=route.url, token_base64=route.token_base64,
                                 to_country_code=country_code, to_party_id=party_id,
                                 from_country_code=we.country_code, from_party_id=we.party_id,
                                 method='GET')
    ic(response)
    return bool(response and response.get('status_code') == status.HTTP_200_OK)


def update_authorization(request, session: Session) -> None:
    try:
        if not session.authorization_reference:
            logging.warning(f'Session {session.uid} has no authorization_reference, cannot link to Authorization.')
            return
        authorization = Authorization.objects.get(authorization_reference=session.authorization_reference)
        if not authorization.session:
            authorization.session = session
            authorization.save(update_fields=['session'])
            logging.info(
                f'Authorization {session.authorization_reference} is now linked to Session {session.uid}'
            )
    except Authorization.DoesNotExist:
        logging.error(f'Authorization {session.authorization_reference} is not known by MSP.', request)


class SessionViewSet(OCPIListModelMixin,
                     GenericViewSet):
    pagination_class = OCPIPaginationAndHeaders
    lookup_field = 'uid'
    queryset = Session.objects.all().order_by('created')
    serializer_class = SessionSerializer
    renderer_classes = RENDERERS
    versioning_class = OCPIVersioning

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'Session {self.kwargs.get("uid")}'
        if self.name:
            return f'{self.name.capitalize()}'
        return f'Sessions'

    @staticmethod
    def get_object(uid=None):
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Session, uid=uid)

    @ocpi_exception_handler
    @requires_credentialsrole
    @certification_step(OcpiModuleEnum.SESSIONS, 'GET a Session which belongs to you')
    def get(self, request, credentialsrole, uid, **_kwargs):
        session = Session.objects.get(uid=uid, ocpi_master=credentialsrole)
        serializer = SessionSerializer(session, many=False, context={'request': request, 'version': request.version})
        return OCPIResponse(serializer.data)

    @classmethod
    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.CPO)
    @certification_step(OcpiModuleEnum.SESSIONS, 'PUT an individual Session with URL parameters')
    def put(cls, request, country_code=None, party_id=None, uid=None, partial=False, data=None, tryagain=False,
            logentry=None, **kwargs) -> OCPIResponse:

        if not request.party_specified_in_url:
            return OCPIResponseUrlParametersRequired('session')

        uid = uid or data.get('id')
        session: Session = Session.get_if_exists(
            uid__iexact=uid, ocpi_master=request.credentialsrole
        )
        created = bool(not session)
        if created and partial:
            return OCPIResponse('Unknown Session UID, unable to PATCH.')

        # Todo: If PATCH fails, we have missed the Session PUT, so we need to fetch the full Session from CPO
        # Todo: Fetch Location if missing
        # Todo: Fetch Tariff if missing
        serializer = SessionSerializer(
            data=request.data, instance=session, partial=partial,
            context={'request': request, 'version': request.version}
        )
        if serializer.is_valid():
            logging.info(f'{"Creating" if created else "Updating"} Session {country_code}*{party_id} - {uid}.',
                         log_to_admin=True, logentry=logentry)
            session = serializer.save(ocpi_master=request.credentialsrole)
            update_authorization(request, session)

            if 'last_updated' not in request.data:
                session.update_last_updated()
            session.send_hub_updates()
            outbound_data = MSPSessionCallbackSerializer.OutboundSerializer(instance=session).data
            send_to_webhook(data, MSPSessionCallbackSerializer, serialized_data=outbound_data)
            stop_session_if_money_runs_out(request, session)
            return OCPIResponse(serializer.data,
                                http_status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

        # Input data doesn't validate
        # Is the Location or EVSE missing?
        if not tryagain and 'evse_uid' in data and 'location_id' in data \
                and ('evse_uid' in serializer.errors or 'location_id' in serializer.errors):
            fetch_location(country_code, party_id, serializer.initial_data.get('location_id'),
                           serializer.initial_data.get('evse_uid'))
            # Try again, but avoid a loop
            return cls.put(request, country_code=kwargs.pop('country_code', country_code),
                           party_id=kwargs.pop('party_id', party_id), uid=kwargs.pop('uid', uid),
                           partial=partial, tryagain=True, **kwargs)
        logging.error('Problem with PUT Session from '
                      f'{request.credentials if hasattr(request, "credentials") else "?"}: {serializer.errors}')
        return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST)

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.CPO)
    @requires_last_updated
    @certification_step(OcpiModuleEnum.SESSIONS, 'PATCH an individual Session',
                        subtopic='Include at least the kwh and last_updated fields')
    def patch(self, request, certification, data, *args, **kwargs):
        if 'kwh' not in data:
            certification.failed('You need to PATCH at least the kwh and the last_updated fields.')
        return self.put(request, *args, partial=True, **kwargs)


class ClientInfoViewSet(mixins.ListModelMixin,
                        GenericViewSet):
    """
    The OCPI Hub Client Info endpoint is used for providing
    information on connection status between roaming parties.
    This view shows as empty when accessing it in the Developer Central,
    but when using OCPI credentials, it will show the actual statuses.
    """
    pagination_class = OCPIPaginationAndHeaders
    serializer_class = ClientInfoSerializer

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'id' in self.kwargs:
            return f'HubClientInfo {self.kwargs.get("id")}'
        return 'HubClientInfo'

    def get_queryset(self):
        if ocpi_platform.is_hub:  # Todo: Maybe better to use inheritance?
            credentialsrole_ids: set = get_partners(self.request)
            if not credentialsrole_ids:
                return CredentialsRole.objects.none()
            return CredentialsRole.objects.\
                filter(pk__in=credentialsrole_ids, credentials__isnull=False).\
                order_by('country_code', 'party_id')
        return CredentialsRole.objects.filter(credentials__isnull=False).order_by('country_code', 'party_id')

    @staticmethod
    def get_object(object_id=None):
        """Needed for OPTIONS to work in list view, could just return None"""
        if object_id:
            return get_object_or_404(CredentialsRole, pk=object_id)

    @certification_step(OcpiModuleEnum.HUBCLIENTINFO, 'GET a list of HubClientInfos',
                        subtopic='')
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.HUB)
    @requires_credentialsrole  # Are you sure?
    @certification_step(OcpiModuleEnum.HUBCLIENTINFO, 'PUT a HubClientInfo',
                        subtopic='')
    def put(self, request, credentialsrole, *_args, **_kwargs):
        serializer = ClientInfoSerializer(
            data=request.data, context={'request': request, 'version': request.version}
        )
        if serializer.is_valid():
            # Todo: Figure out how to create Credentials we don't know about
            return OCPIResponse(serializer.data, http_status=status.HTTP_200_OK)
        return OCPIBadRequestResponse(serializer.errors)


class RootView(routers.APIRootView):
    """
    Welcome to the Developer Central.
    Here you have interactive access to the OCPI 2.2 and 2.2.1 endpoints with examples.

    > **OCPI** is the starting point for the OCPI hierarchy, where the OCPI modules reside.
    >
    > **CPO API** is a cost-effective shortcut to OCPI connectivity.
    >
    > **OpenAPI** provides output which can be imported in popular API browsing tools.
    >
    > **ADMIN UI** link on the top right corner takes you to where you can view and edit the OCPI objects.
    """

    @staticmethod
    def get(request: WSGIRequest, **kwargs):
        result = dict({
            "OCPI 2.2.1": request.build_absolute_uri(reverse('ocpi-221', request=request)),
            # "OpenAPI": request.build_absolute_uri(reverse('openapi-schema', request=request)),
        })
        if ocpi_platform.is_cpo:
            result.update({"CPO API": request.build_absolute_uri(reverse('cpo-api', request=request))})
        if ocpi_platform.is_emsp:
            result.update({"eMSP API": request.build_absolute_uri(reverse('msp-api', request=request))})
        return Response(result)

    def get_view_name(self):
        return 'Developer Central'


class RootRouter(routers.DefaultRouter):
    APIRootView = RootView
    root_view_name = 'root'


class OcpiApi22View(routers.APIRootView):
    """
    This is the OCPI "endpoints" endpoint. The other party will cache this information to be able to contact
    the available endpoints to update and mirror data structures.
    """

    versioning_class = OCPIVersioning

    @staticmethod
    def get(request, **kwargs):
        return OCPIResponse(get_endpoints_dict(request))

    def get_view_name(self):
        return 'Endpoints'


class OCPIRouter(routers.DefaultRouter):
    APIRootView = OcpiApi22View
    root_view_name = 'ocpi-22'

    # Make trailing slash optional in URLs
    def __init__(self):
        super().__init__()
        self.trailing_slash = '/?'
