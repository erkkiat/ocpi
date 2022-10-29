import json

from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator

import ocpi22.logging as logging
from decimal import Decimal

import requests
from django.conf import settings
from django.utils.translation import get_language
from rest_framework import routers, status, viewsets, mixins
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.viewsets import GenericViewSet

from ocpi22.choices import OcpiRolesEnum
from ocpi22.commands.commands import send_start_command, send_stop_command, send_reserve_command
from ocpi22.commands.serializers import CommandResultSerializer
from ocpi22.cpo.serializers import TariffQuickSerializer
from ocpi22.generic_views import WebhookViewSet
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session
from ocpi22.models.tariff import Tariff
from ocpi22.models.token import Token
from ocpi22.msp.serializers import StartChargingSerializer, StopChargingSerializer, SessionStatusSerializer, \
    MspSessionSerializer, MSPCallbacksSerializer, MSPAuthorizeCallbackSerializer, ReserveSerializer
from ocpi22.msp.util import get_message_by_language
from ocpi22.ocpi.api import TokenViewSet
from ocpi22.ocpi.serializers import MspAuthorizationResponseSerializer
from ocpi22.ocpi.util import OCPIResponse
from ocpi22.sessions.util import get_session
from ocpi22.tokens.util import construct_adhoc_token
# from ocpiconnector import slack_logging

from ocpiconnector.ocpi_identities import get_our_party


# slack_logging.init()


# Todo: Handle gracefully situation where CPO backend is offline (now 503)

# Todo: limit access to certain privilege holders


class MspRoamingViewSet(viewsets.GenericViewSet):
    """
    """
    queryset = Token.objects.all()
    lookup_field = 'uid'
    permission_classes = [IsAuthenticated]
    publicly_visible = True  # Don't use the OCPI authentication, just require basic auth or OAuth2

    def get_serializer_class(self):
        return dict(
            start_charging=StartChargingSerializer,
            session_status=SessionStatusSerializer,
            stop_charging=StopChargingSerializer,
            reserve=ReserveSerializer,
        ).get(self.action_map.get('post'), None)

    @action(methods=('GET', 'POST'), detail=False)
    def reserve(self, request):
        """
        This call sends an OCPI ReserveNow command to the CPO.

        ## Status codes

        * `HTTP_200_OK` when the reservation was made successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_404_NOT_FOUND` when the Token, Location or EVSE doesn't exist
        * `HTTP_422_UNPROCESSABLE_ENTITY` when the response from CPO is broken
        * `HTTP_503_SERVICE_UNAVAILABLE` when there is no network connection to the charge point
        """

        # Todo: Fail if no Tariffs for any Connector in this EVSE

        try:
            if request.method == 'POST':
                serializer = ReserveSerializer(data=request.data)
                if serializer.is_valid():
                    account = request.user.accounts.first()
                    if settings.REQUIRE_WALLET_BALANCE and account.balance <= Decimal("2.0"):
                        return Response(dict(
                            status_message='There is not enough balance in the account to make a reservation'),
                            status=status.HTTP_402_PAYMENT_REQUIRED
                        )
                    location: Location = serializer.validated_data['location']
                    evse: Evse = serializer.validated_data['evse']
                    reservation_id: str = serializer.validated_data.get('reservation_id')
                    connector_id: str = serializer.validated_data.get('connector_id')
                    contract_id: str = serializer.validated_data.get('contract_id')
                    token = construct_adhoc_token(account.app_token_id, contract_id)
                    expiration: int = serializer.validated_data.get('expiration')
                    ic(
                        request, evse, token, connector_id, contract_id, expiration, reservation_id
                    )
                    response: requests.Response = send_reserve_command(
                        request, location, evse, token, reservation_id, connector_id, contract_id, expiration
                    )
                    return self._language_response(response)
                else:
                    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response(dict(help='Please see `OPTIONS` for the schema'), status=status.HTTP_400_BAD_REQUEST)
        except (Evse.DoesNotExist, Token.DoesNotExist, Location.DoesNotExist, Connector.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)
        except json.JSONDecodeError as e:
            logging.error(f'Cannot process start_transaction response from CPO to eMSP: {e}', request=request)
            return Response(
                dict(status=str(e)),
                status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

    @action(methods=('GET', 'POST'), detail=False)
    def start_charging(self, request):
        """
        This call starts the charging transaction (which equals the OCPI session in the roaming network).

        ## Status codes

        * `HTTP_200_OK` when the charging session was started successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_402_PAYMENT_REQUIRED` when the user account doesn't have enough balance for charging
        * `HTTP_404_NOT_FOUND` when the Token, Location or EVSE doesn't exist
        * `HTTP_422_UNPROCESSABLE_ENTITY` when the response from CPO is broken
        * `HTTP_503_SERVICE_UNAVAILABLE` when there is no network connection to the charge point
        """

        # Todo: Fail if no Tariffs for any Connector in this EVSE

        try:
            if request.method == 'POST':
                serializer = StartChargingSerializer(data=request.data)
                if serializer.is_valid():
                    account = request.user.accounts.first()
                    if settings.REQUIRE_WALLET_BALANCE and account.balance <= Decimal("2.0"):
                        return Response(dict(
                            status_message='There is not enough balance in the account to start charging'),
                            status=status.HTTP_402_PAYMENT_REQUIRED
                        )
                    evse: Evse = serializer.validated_data['evse']
                    connector_id: str = serializer.validated_data.get('connector_id')
                    contract_id: str = serializer.validated_data.get('contract_id')
                    token = construct_adhoc_token(account.app_token_id, contract_id)
                    response: requests.Response = send_start_command(request, evse, token, connector_id, contract_id)
                    # ic(response)
                    return self._language_response(response)
                else:
                    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response(dict(help='Please see `OPTIONS` for the schema'), status=status.HTTP_400_BAD_REQUEST)
        except (Evse.DoesNotExist, Token.DoesNotExist, Location.DoesNotExist, Connector.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)
        except json.JSONDecodeError as e:
            logging.error(f'Cannot process start_transaction response from CPO to eMSP: {e}', request=request)
            return Response(
                dict(status=str(e)),
                status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

    @action(methods=('GET', 'POST'), detail=False)
    def session_status(self, request):
        """
        Get the status of the ongoing session for this user. Currently only one session at a time is supported.

        ## Status codes

        * `HTTP_200_OK` when the charging session is ongoing and status is available
        * `HTTP_404_NOT_FOUND` when the Session doesn't exist or status is not yet available
        """
        try:
            serializer = SessionStatusSerializer(data=request.data)
            if serializer.is_valid():
                session = serializer.validated_data.get('session')
                if not session:
                    token = request.user.accounts.first().app_token_id
                    session = get_session(token, (Session.PENDING, Session.ACTIVE, Session.COMPLETED, Session.INVALID))
                    if not session:
                        return Response(dict(status=f'No session found for token `{token}`. '
                                                    f'There may not have been a Session update from CPO.'),
                                        status=status.HTTP_404_NOT_FOUND)
                data = MspSessionSerializer(instance=session).data
                messages = data.get('message')
                if messages:
                    data.update(message_display=get_message_by_language(messages, get_language()))
                return Response(data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except (Evse.DoesNotExist, Token.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)

    @staticmethod
    def _language_response(response):
        data = response.json()
        data = data.get('data', data) or data
        message = data.get('message')
        if message:
            data.update(message_display=get_message_by_language(data.get('message'), get_language()))
        else:
            data.update(message_display=data.get('status_message'))
        return Response(data, status=response.status_code)

    @action(methods=('GET', 'POST'), detail=False)
    def stop_charging(self, request):
        """
        This call stops the charging transaction.

        ## Status codes

        * `HTTP_200_OK` when the charging session was stopped successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_404_NOT_FOUND` when the Token or the EVSE doesn't exist
        * `HTTP_422_UNPROCESSABLE_ENTITY` when the response from CPO is broken
        """
        try:
            if request.method == 'POST':
                serializer = StopChargingSerializer(data=request.data)
                if serializer.is_valid():
                    session = serializer.validated_data.get('session')
                    if not session:
                        token = request.user.accounts.first().app_token_id
                        session = get_session(token)
                        if not session:
                            return Response(dict(status=f'No active session found for token `{token}`. '
                                                        f'There may not have been a Session update from CPO.'),
                                            status=status.HTTP_404_NOT_FOUND)
                    response: requests.Response = send_stop_command(session)
                    return self._language_response(response)
                else:
                    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response(dict(help='Please see `OPTIONS` for the schema'), status=status.HTTP_400_BAD_REQUEST)
        except (Evse.DoesNotExist, Token.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)
        except (json.JSONDecodeError, AttributeError, ValidationError) as e:
            logging.error(f'Unable to process start_transaction response from CPO to eMSP: {e}', request=request)
            return Response(
                dict(status_message=f'Unable to process response from CPO: {e}'),
                status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

    def get_return_values_serializer(self):
        return dict(
            start_charging=CommandResultSerializer(),
            stop_charging=CommandResultSerializer(),
        ).get(self.action_map.get('post'))

    def get_view_name(self):
        if self.name:
            return f'{self.name.capitalize()}'
        return f'Status Change'

    @staticmethod
    def get_object(uid=None) -> None:
        # Needed for OPTIONS to work in list view
        return None


class MspTokenViewSet(TokenViewSet):
    """
    **GET**: List active and inactive Tokens.

    **PUT**: Create or update a Token (usually an RFID).
    Country_code and party_id are set automatically according to your MSP identity.

    **PATCH**: Update a Token.
    """

    def check_ownership(self, token) -> bool:
        # The MSP can always update, and we force the country_code and party_id to match
        return True

    def put(self, request, country_code=None, party_id=None, uid=None, data=None, partial=None):
        party = get_our_party(OcpiRolesEnum.EMSP)
        data = request.data
        data['country_code'] = party.country_code
        data['party_id'] = party.party_id

        result: OCPIResponse = super().put(request, party.country_code, party.party_id, uid, data)
        return Response(result.data.get('data'))

    def patch(self, request):
        return self.put(request, partial=True)

    def list(self, request):
        result: OCPIResponse = super().list(request)
        return Response({'data': result.data.get('data')})

    def authorize(self, request, token_uid):
        pass


class MspAuthorizeWebhookViewSet(WebhookViewSet):
    """
    You need to tell the OCPI Connector where to check for authorization of a specific RFID.
    Using this endpoint you can set and get your callback URL and
    user credentials needed for accessing the endpoint.

    Example URL: `https://your.emsp.backend.server/authorize/{token_id}/`. The token_id will be substituted with
    the corresponding parameter from the data sent to this URL. For details, please use "OPTIONS".

    > **BASIC AUTHENTICATION**: Include user credentials and port in URL,
    > for example `https://user:password@example.com:1234/path/to/my/endpoint/`.

    ## Status codes

    * `HTTP_200_OK` when the webhook was set successfully
    * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
    """
    serializer_class = MSPCallbacksSerializer
    serializer = serializer_class()
    queryset = Token.objects.none()

    authorize_callback_serializer = MSPAuthorizeCallbackSerializer()

    def get_extra_metadata(self, _request) -> dict:
        return dict(authorize_webhook_details=dict(
            data_sent=self.metadata.get_serializer_info(self.authorize_callback_serializer),
            expected_result=self.metadata.get_serializer_info(MspAuthorizationResponseSerializer())
        )
        )

    @action(methods=('GET', 'POST', 'PATCH'), detail=False, url_path='authorize')
    def authorize_webhook(self, request):
        return self.webhook(request)


class MobilityServiceProviderAPIView(routers.APIRootView):
    """
    This API is not a part of the OCPI protocol. It is intended as fast shortcut to OCPI roaming.

    > Here you can use the eMSP API interfaces intearactively
    > to support your development and integration work.
    > These streamlined interfaces provide the necessary tools for quickly but comprehensively connecting
    > an eMSP backend to CPOs and hubs using the OCPI protocol.

    **ADMIN UI**: All the objects in the OCPI Connector are available for browsing
    and selective modification in the admin tools.
    It also provides tools for maintaining users, groups and their access to the OCPI Connector.

    For more details, click the links below and you will find the step-by-step technical documentation.

    """

    @method_decorator(login_required)
    def get(self, request, *args, **kwargs):
        """
        Compile the example URLs for the root page
        """

        result = dict(
            charging=dict(
                reserve=request.build_absolute_uri(
                    reverse('roaming-reserve')
                ),
                start_charging=request.build_absolute_uri(
                    reverse('roaming-start-charging')
                ),
                session_status=request.build_absolute_uri(
                    reverse('roaming-session-status')
                ),
                stop_charging=request.build_absolute_uri(
                    reverse('roaming-stop-charging')
                ),
            ),
            authorization=dict(
                tokens=request.build_absolute_uri(
                    reverse('msp-token-list'),
                ),
                authorize_webhook=request.build_absolute_uri(
                    reverse('msp-authorize-webhook'),
                ),
            ),
            user=dict(
                register=request.build_absolute_uri(
                    reverse('user-register')
                ),
                account=request.build_absolute_uri(
                    reverse('user-account')
                ),
                password=request.build_absolute_uri(
                    reverse('user-password')
                ),
                transactions_brief=request.build_absolute_uri(
                    reverse('user-transaction-list-brief')
                ),
                transactions_full=request.build_absolute_uri(
                    reverse('user-transaction-list-full')
                ),
                car_details=request.build_absolute_uri(
                    reverse('user-car-details')
                ),
            ),
            billing=dict(
                cdr_list=request.build_absolute_uri(
                    reverse('msp-cdr-list')
                ),
                tariff_list=request.build_absolute_uri(
                    reverse('msp-tariff-list')
                ),
            ),
            navigation=dict(
                charge_points=request.build_absolute_uri(
                    reverse('map-locations')
                ),
                car_models=request.build_absolute_uri(
                    reverse('msp-cars-list')
                ),
            ),
        )
        return Response(result)

    def get_view_name(self):
        return 'eMobility Service Provider API'


class MspTariffQuickViewSet(mixins.ListModelMixin,
                            mixins.RetrieveModelMixin,
                            GenericViewSet):
    """
    This is the endpoint for listing tariffs with a simplified structure. If you need to view the complex
    Tariffs, use the OCPI Tariff endpoints.

    To get a single Quick Tariff, append the Tariff ID to the URL, e.g. .../T1/
    """
    queryset = Tariff.objects.all().filter(archived=False).order_by('uid')
    serializer_class = TariffQuickSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = 'uid'

    def retrieve(self, request, *args, uid, **kwargs):
        tariff = get_object_or_404(Tariff, uid=uid, archived=False)
        serializer = self.serializer_class(instance=tariff)
        return Response(serializer.data)

    @staticmethod
    def get_object(uid=None) -> Tariff:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Tariff, uid=uid)


class MSPRouter(routers.DefaultRouter):
    APIRootView = MobilityServiceProviderAPIView
    root_view_name = 'msp-api'
