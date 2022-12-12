from django.conf import settings
from rest_framework.exceptions import ValidationError

import ocpi22.logging as logging
from typing import Optional

import requests
from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django_filters.rest_framework import DjangoFilterBackend
from icecream import ic
from rest_framework import routers, status, mixins
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.viewsets import GenericViewSet

from ocpi22.choices import MessageTexts, get_language, AuthorizationEnum
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
from ocpi22.util import matching_operator, OnlyRawBrowsableAPIRenderer, build_callback_request
from ocpi22.ocpi.util import OCPIBadRequestResponse, NotOwner, OCPIResponse, Ocpi, OCPIPaginationAndHeaders, \
    generate_auth_reference
from ocpi22.credentials.versions import get_endpoints_dict
from ocpiconnector.management.commands.exchange_credentials import get_our_roles, select_version, get_endpoints
from ocpiconnector.ocpi_identities import ocpi_platform
from premium import requires_premium


# Todo: In case a PATCH request fails, the client is expected to call the GET method to check the state
#  of the object in the other party’s system. If the object doesn’t exist, the client should do a PUT.

# Todo: Only requests/responses from Function Modules: such as: Tokens, Locations, CDRs etc. SHALL be routed,
#  so need the routing headers.


class TokenViewSet(mixins.ListModelMixin,
                   GenericViewSet):
    queryset = Token.objects.all().order_by('created')
    serializer_class = TokenSerializer
    pagination_class = OCPIPaginationAndHeaders
    lookup_field = 'uid'
    renderer_classes = RENDERERS
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['country_code', 'party_id', 'type']

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'Token {self.kwargs.get("uid")}'
        if self.name:
            return f'{self.name.capitalize()}'
        return f'Tokens'

    @staticmethod
    def get_object(uid=None) -> Optional[Token]:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Token, uid=uid)

    def check_ownership(self, token) -> bool:
        return token and token.is_ours()

    @transaction.atomic
    def put(self, request, country_code=None, party_id=None, uid=None, data=None, partial=False):
        data = data or request.data.get('data', request.data)
        uid = uid or data.get('uid')
        party_id = party_id or data.get('party_id')
        country_code = country_code or data.get('country_code')

        token: Token = Token.get_if_exists(uid=uid, party_id=party_id, country_code=country_code)

        if self.check_ownership(token) is True:
            return OCPIResponse(f'Object {token} is owned by us and cannot be updated from outside.',
                                http_status=status.HTTP_401_UNAUTHORIZED,
                                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

        if token and request and not token.is_owner(request):
            return NotOwner()
        serializer = TokenSerializer(data=data, instance=token, partial=partial)
        if serializer.is_valid():
            logging.info(f'Creating or updating Token {country_code}*{party_id} - {uid}.')
            serializer.save()
            Token.send_hub_updates(serializer.data)
            return OCPIResponse(serializer.data, http_status=status.HTTP_200_OK if token else status.HTTP_201_CREATED)
        else:
            return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request):
        return self.put(request, partial=True)

    @csrf_exempt
    @action(methods=['POST', 'GET'], detail=False,
            url_path='(?P<token_uid>[^/.]+)/authorize')
    def authorize(self, request: Request, token_uid) -> OCPIResponse:
        allowed = AuthorizationEnum.ALLOWED.value
        ocpi_status = Ocpi.OK
        http_status = 200
        info = None
        status_message = 'Success'
        user_language = 'en'

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
                    location_name = f'{location.name} at {location.address}, {location.city}'
                    prices = location.get_prices_str()
                else:
                    return OCPIResponse(serializer.errors)
            else:
                location_name = '-'
                prices = 'not available'

            if token.language:
                user_language = token.language.lower()

            if not token.valid:
                allowed = AuthorizationEnum.EXPIRED.value
                info = MessageTexts.get('TOKEN_NOT_VALID')
                ocpi_status = 2000
                http_status = status.HTTP_401_UNAUTHORIZED
                status_message = 'Your charging token is not valid at the moment'
                message_user(status_message, '+358405480238')

            data = {'token_id': token_uid}
            serializer = MSPAuthorizeCallbackSerializer.OutboundSerializer(data=data)
            assert serializer.is_valid()

            # Todo: Update tests for internal accounting and create tests for MSP authorize callback

            authorize_token_url, kwargs_update = build_callback_request(MSPAuthorizeCallbackSerializer.URL, data)

            if authorize_token_url:
                kwargs = {}
                headers = {'content-type': 'application/json'}
                kwargs.update(kwargs_update)

                logging.info(f'Calling MSP authorize webhook at url {authorize_token_url}')
                msp_response = requests.post(
                    url=authorize_token_url,
                    json=serializer.data,
                    headers=headers,
                    verify=False,
                    timeout=28,  # Just under the 30 second limit which is maximum for Heroku requests
                    **kwargs)
                data = msp_response.json()
                serializer = MSPAuthorizeCallbackSerializer.ResponseSerializer(data=data)
                if serializer.is_valid():
                    allowed = data.get('result', 'NOT_ALLOWED').upper()
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
                    allowed = AuthorizationEnum.NO_CREDIT.value
                    info = MessageTexts.get('NO_BALANCE')
                    ocpi_status = Ocpi.ClientError.GENERIC_CLIENT_ERROR
                    http_status = status.HTTP_401_UNAUTHORIZED
                    status_message = get_language(user_language, info)
                    # message_user(status_message, '+358405480238')

            # if allowed == AuthorizationEnum.ALLOWED.value:
            #     message = UserMessages.approve_charging.get(user_language)
            #     ic(message)
            #     message_user(message, '+358405480238', location=location_name,
            #                  price=prices, url="http://secureautocharge.com/132244/")

            serializer = TokenSerializer(instance=token)
            return OCPIResponse(
                dict(
                    allowed=allowed,
                    token=serializer.data,
                    # Todo: Store authorization in billing system
                    authorization_reference=generate_auth_reference() if allowed == AuthorizationEnum.ALLOWED.value else '',
                ), status_code=ocpi_status, status=http_status, status_message=status_message
            )
        except ValueError as e:
            return OCPIResponse(
                {},
                status_code=Ocpi.ServerError.GENERIC_SERVER_ERROR,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
                status_message=f'{get_language(user_language, info)}: {str(e)}'
            )

    def get(self, request, country_code=None, party_id=None, uid=None):
        if country_code and party_id and uid:
            token = get_object_or_404(Token, country_code=country_code, party_id=party_id, uid=uid)
            serializer = TokenSerializer(token, many=False, context={'request': request})
            return OCPIResponse(serializer.data)
        return OCPIBadRequestResponse()

    @action(methods=['PUT', 'PATCH'], detail=False, url_name='by-id',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def token_by_id(self, request, country_code, party_id, uid) -> OCPIResponse:
        token = get_object_or_404(Token, country_code=country_code, party_id=party_id, uid=uid)

        # Method is PUT or PATCH
        if not token.is_owner(request):
            return NotOwner()

        method_is_patch = bool(request.method == 'PATCH')

        serializer = TokenSerializer(token,
                                     data=request.data,
                                     partial=method_is_patch,
                                     context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return OCPIResponse(serializer.data)

        return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST)


class CdrViewSet(mixins.ListModelMixin,
                 GenericViewSet):
    """
    These are the records created for the purpose of billing. Once a CDR is created, it must not be modified or removed.
    A CDR can be credited to the customer by creating a credit CDR in the admin tools.
    **VISIBILITY**: A CDR record is only available to relevant parties,
    so fetching another party's CDR should not be allowed. (When logged in as a superuser, you can see all CDRs)
    """
    # noinspection PyUnresolvedReferences
    queryset = Cdr.objects.none()  # Default to no visibility, fine tune with get_queryset()
    serializer_class = CdrSerializer
    pagination_class = OCPIPaginationAndHeaders
    renderer_classes = RENDERERS

    def get_queryset(self):
        if self.request.user.is_superuser:
            return Cdr.objects.all().order_by('created')
        if hasattr(self.request, 'country_code'):
            ic(self.request.country_code, self.request.party_id)
            return Cdr.objects.filter(
                country_code=self.request.country_code,
                party_id=self.request.party_id
            ).order_by('created')
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

    @action(methods=['GET'], detail=False,
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    @requires_premium
    def by_id(self, request, country_code=None, party_id=None, uid=None) -> Response:
        cdr = get_object_or_404(Cdr, country_code=country_code, party_id=party_id, uid=uid)
        serializer = CdrSerializer(cdr, many=False, context={'request': request})
        return OCPIResponse(serializer.data)

    @transaction.atomic
    @requires_premium
    def put(self, request) -> OCPIResponse:
        data = request.data.get('data', request.data)
        country_code = data.get('country_code')
        party_id = data.get('party_id')

        if not matching_operator(request, country_code, party_id):
            return NotOwner()

        serializer = CdrSerializer(data=data)
        if serializer.is_valid():
            cdr = serializer.save()
            # cdr.tariffs.set(tariff_list)
            Cdr.send_hub_updates(serializer.data)
            if ocpi_platform.is_emsp:
                update_balance(cdr)
            return OCPIResponse(serializer.data, http_status=status.HTTP_201_CREATED)
        return OCPIResponse(errors=serializer.errors)


def make_my_credentials_dict(request) -> dict:
    return dict(
        token=request.credentials.ours
        if hasattr(request, 'credentials') else 'not available when using basic auth',

        url=request.build_absolute_uri(reverse('base-versions')),

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

    @requires_premium
    def list(self, request, *_args, **_kwargs):
        return OCPIResponse(make_my_credentials_dict(request))

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

    @requires_premium
    @csrf_exempt
    def post(self, request: Request, *_args, **_kwargs):
        try:
            assert hasattr(request, 'credentials'), f'Posting to this endpoint requires OCPI Credentials'
            data = request.data
            data = data.get('data', data)
            credentials: Credentials = request.credentials
            credentials.theirs = data.get('token')
            credentials.url = data.get('url')
            credentials.roles.all().delete()

            for role in data['roles']:
                credentials.add_role(role)

            # Delay storing tokens until now, in case the roles have some issue
            credentials.save()

            token_base64 = credentials.theirs_base64()  # CREDENTIALS_TOKEN_B
            selected_version = select_version(credentials.url, token_base64)
            endpoints = get_endpoints(selected_version['url'], token_base64)
            store_endpoints_for_party(credentials, endpoints)
            data = make_my_credentials_dict(request)
            serializer = CredentialsSerializer(data=data)
            if not serializer.is_valid():
                logging.error(f'OCPI connector has a logic error in Credentials POST: {serializer.errors}')
                return Response(
                    dict(
                        status_text='Sorry, but we have a slight problem. Support has been alerted.'
                    ),
                    status=status.HTTP_503_SERVICE_UNAVAILABLE)
            return OCPIResponse(serializer.data)
        except (ValidationError, AssertionError, KeyError) as e:
            logging.error(str(e), request)
            return OCPIBadRequestResponse(str(e))


class TariffViewSet(mixins.ListModelMixin,
                    GenericViewSet):
    queryset = Tariff.objects.exclude(archived=True).order_by('created')
    serializer_class = TariffSerializer
    pagination_class = OCPIPaginationAndHeaders
    lookup_field = 'uid'
    renderer_classes = RENDERERS

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'Tariff {self.kwargs.get("uid")}'
        if self.name:
            return f'{self.name.capitalize()}'
        return 'Tariffs'

    @requires_premium
    def list(self, *args, **kwargs):
        return super().list(*args, **kwargs)

    @action(methods=['GET'], detail=False, description='Get a single Tariff by country, party and uid',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)', url_name='by-id')
    @requires_premium
    def tariff_by_id(self, request, country_code, party_id, uid) -> OCPIResponse:
        tariff = get_object_or_404(Tariff, country_code=country_code, party_id=party_id, uid=uid, archived=False)
        serializer = TariffSerializer(tariff, many=False, context={'request': request})
        return OCPIResponse(serializer.data)

    @staticmethod
    def get_object(uid=None) -> Tariff:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Tariff, uid=uid)

    @requires_premium
    @transaction.atomic
    def put(self, request, country_code=None, party_id=None, uid=None, data=None) -> OCPIResponse:
        # This PUT is used both for the Tariff endpoint root and the path with country_code, party_id and Tariff uid
        data = data or request.data.get('data', request.data)
        country_code = country_code or data.get('country_code')
        party_id = party_id or data.get('party_id')
        uid = uid or data.get('id')

        if request and not matching_operator(request, country_code, party_id):
            return NotOwner()

        tariff: Tariff = Tariff.get_if_exists(country_code=country_code, party_id=party_id, uid=uid,
                                              archived=False)
        if tariff and tariff.is_ours():
            return OCPIResponse(f'Tariff {tariff} is owned by us and cannot be updated from outside.',
                                http_status=status.HTTP_401_UNAUTHORIZED,
                                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)
        serializer = TariffSerializer(instance=tariff, data=data)
        if serializer.is_valid():
            logging.info(f'Creating or updating Tariff {country_code}*{party_id} - {uid}.')
            serializer.save()
            Tariff.send_hub_updates(data)
            return OCPIResponse(serializer.data, http_status=status.HTTP_200_OK if tariff else status.HTTP_201_CREATED)
        else:
            return OCPIResponse(errors=serializer.errors)


class SessionViewSet(mixins.ListModelMixin,
                     GenericViewSet):
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['country_code', 'party_id', 'status', 'meter_id', 'cdr_token_uid', 'authorization_reference']
    pagination_class = OCPIPaginationAndHeaders
    lookup_field = 'uid'
    # noinspection PyUnresolvedReferences
    queryset = Session.objects.all().order_by('created')
    serializer_class = SessionSerializer
    renderer_classes = RENDERERS

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

    @transaction.atomic
    @action(methods=['GET'], detail=False, url_name='by-id',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def session_by_id(self, request, country_code, party_id, uid) -> OCPIResponse:
        session = get_object_or_404(Session, country_code=country_code, party_id=party_id, uid=uid)

        if request.method == 'GET':
            serializer = SessionSerializer(session, context={'request': request})
            return OCPIResponse(serializer.data)

        return OCPIResponse(http_status=status.HTTP_400_BAD_REQUEST)

    @staticmethod
    @transaction.atomic
    def put(request, country_code=None, party_id=None, uid=None, partial=False) -> OCPIResponse:
        data = request.data.get('data', request.data)
        uid = uid or data.get('uid')
        country_code = country_code or data.get('country_code')
        party_id = party_id or data.get('party_id')
        created = True
        session: Session = Session.get_if_exists(uid=uid, party_id=party_id, country_code=country_code)
        if session:
            logging.info(f'Received an update for session {uid} from {country_code}*{party_id}')
            created = False
            if not session.is_owner(request):
                return NotOwner()
            if session.is_final():
                return OCPIResponse('Cannot update a completed Session.', http_status=status.HTTP_401_UNAUTHORIZED,
                                    status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)
        else:
            logging.info(f'Creating new session {uid} received from {country_code}*{party_id}')
        serializer = SessionSerializer(
            data=request.data, instance=session, partial=partial, context={'request': request}
        )
        if serializer.is_valid():
            session = serializer.save()
            if 'last_updated' not in request.data:
                session.update_last_updated()
            Session.send_hub_updates(serializer.data)
            outbound_data = MSPSessionCallbackSerializer.OutboundSerializer(instance=session).data
            send_to_webhook(data, MSPSessionCallbackSerializer, serialized_data=outbound_data)
            return OCPIResponse(serializer.data,
                                http_status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
        logging.error(f'Problem with PUT Session from {request.credentials}: {serializer.errors}')
        return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, country_code=None, party_id=None, uid=None):
        return self.put(request, country_code, party_id, uid, partial=True)


class ClientInfoViewSet(mixins.ListModelMixin,
                        GenericViewSet):
    filterset_fields = ['country_code', 'party_id']
    pagination_class = OCPIPaginationAndHeaders
    # lookup_field = 'pk'
    # noinspection PyUnresolvedReferences
    queryset = CredentialsRole.objects.all().order_by('country_code', 'party_id')
    serializer_class = ClientInfoSerializer

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'id' in self.kwargs:
            return f'HubClientInfo {self.kwargs.get("id")}'
        # if self.name:
        #     return f'{self.name.capitalize()}'
        return f'HubClientInfo'

    @staticmethod
    def get_object(id=None):
        # Needed for OPTIONS to work in list view, could just return None
        if id:
            return get_object_or_404(CredentialsRole, pk=id)


class RootView(routers.APIRootView):
    """
    Welcome to the OCPI Connector Developer Central.
    Here you have interactive access to the OCPI 2.2 endpoints with examples.

    > **OCPI 2.2** is the starting point for the OCPI hierarchy, where the OCPI modules reside.
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
            "OCPI 2.2": request.build_absolute_uri(reverse('ocpi-22')),
            # "OpenAPI": request.build_absolute_uri(reverse('openapi-schema')),
        })
        if ocpi_platform.is_cpo:
            result.update({"CPO API": request.build_absolute_uri(reverse('cpo-api'))})
        if ocpi_platform.is_emsp:
            result.update({"eMSP API": request.build_absolute_uri(reverse('msp-api'))})
        return Response(result)

    def get_view_name(self):
        return 'OCPI Connector Developer Central'


class RootRouter(routers.DefaultRouter):
    APIRootView = RootView
    root_view_name = 'root'


class OcpiApi22View(routers.APIRootView):
    """
    This is the OCPI "endpoints" endpoint. The other party will cache this information to be able to contact
    the available endpoints to update and mirror data structures.
    """

    @staticmethod
    def get(request, **kwargs):
        return OCPIResponse(get_endpoints_dict(request))

    def get_view_name(self):
        return 'OCPI 2.2'


class OCPIRouter(routers.DefaultRouter):
    APIRootView = OcpiApi22View
    root_view_name = 'ocpi-22'

    # Make trailing slash optional in URLs
    def __init__(self):
        super().__init__()
        self.trailing_slash = '/?'
