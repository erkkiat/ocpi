import json
import logging
from decimal import Decimal

import requests
from django.utils.translation import get_language
from icecream import ic
from rest_framework import routers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.reverse import reverse

from ocpi22.commands.commands import send_start_command, send_stop_command
from ocpi22.commands.serializers import CommandResultSerializer
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.msp.serializers import StartChargingSerializer, StopChargingSerializer, SessionStatusSerializer, \
    MspSessionSerializer
from ocpi22.msp.util import get_message_by_language
from ocpi22.sessions.util import get_session
from ocpi22.tokens.util import construct_adhoc_token
from ocpiconnector import slack_logging

from pprint import PrettyPrinter

pp = PrettyPrinter(indent=4).pprint
slack_logging.init()


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
        ).get(self.action_map.get('post'), StartChargingSerializer)

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
        * `HTTP_424_FAILED_DEPENDENCY` when there is no network connection to the charge point
        """

        # Todo: Fail if no Tariffs for any Connector in this EVSE

        try:
            if request.method == 'POST':
                serializer = StartChargingSerializer(data=request.data)
                if serializer.is_valid():
                    account = request.user.accounts.first()
                    if account.balance <= Decimal("2.0"):
                        return Response(dict(
                            status_message='There is not enough balance in the account to start charging'),
                            status=status.HTTP_402_PAYMENT_REQUIRED
                        )
                    evse: Evse = serializer.validated_data['evse']
                    connector_id: str = serializer.validated_data.get('connector_id')
                    contract_id: str = serializer.validated_data.get('contract_id')
                    token = construct_adhoc_token(account.app_token_id, contract_id)
                    response: requests.Response = send_start_command(request, evse, token, connector_id, contract_id)
                    data = response.json()
                    return Response(data.get('data'), status=response.status_code)
                else:
                    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response(dict(help='Please see `OPTIONS` for the schema'), status=status.HTTP_400_BAD_REQUEST)
        except (Evse.DoesNotExist, Token.DoesNotExist, Location.DoesNotExist, Connector.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)
        except json.JSONDecodeError as e:
            logging.error(f'Cannot process start_transaction response from CPO to eMSP: {e}')
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
                data.update(message_display=get_message_by_language(data.get('message'), get_language()))
                return Response(data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except (Evse.DoesNotExist, Token.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)

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
                    data = response.json()
                    return Response(data.get('data'), status=response.status_code)
                else:
                    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response(dict(help='Please see `OPTIONS` for the schema'), status=status.HTTP_400_BAD_REQUEST)
        except (Evse.DoesNotExist, Token.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)
        except (json.JSONDecodeError, AttributeError, ValidationError) as e:
            logging.error(f'Unable to process start_transaction response from CPO to eMSP: {e}')
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

    # noinspection PyUnresolvedReferences
    def get(self, request, *args, **kwargs):
        """
        Compile the example URLs for the root page
        """

        result = dict(
            remote_commands_to_cpo=dict(
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
                )
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


class MSPRouter(routers.DefaultRouter):
    APIRootView = MobilityServiceProviderAPIView
    root_view_name = 'msp-api'
