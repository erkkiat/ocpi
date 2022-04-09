import json
import logging
import requests
from rest_framework import routers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.reverse import reverse

from ocpi22.commands.commands import send_start_command, send_stop_command
from ocpi22.commands.serializers import CommandResult
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.token import Token
from ocpi22.msp.serializers import StartChargingSerializer, StopChargingSerializer
from ocpi22.tokens import construct_adhoc_token
from ocpiconnector import slack_logging

from pprint import PrettyPrinter

pp = PrettyPrinter(indent=4).pprint
slack_logging.init()


# Todo: limit access to certain privilege holders
class MspRoamingViewSet(viewsets.GenericViewSet):
    """
    """
    # noinspection PyUnresolvedReferences
    queryset = Location.objects.all()
    lookup_field = 'uid'

    def get_serializer_class(self):
        return dict(
            start_charging=StartChargingSerializer,
            stop_charging=StopChargingSerializer,
        ).get(self.action_map.get('post'), StartChargingSerializer)

    @action(methods=('GET', 'POST'), detail=False)
    def start_charging(self, request):
        """
        This call starts the charging transaction (which equals the OCPI session in the roaming network).

        ## Status codes

        * `HTTP_200_OK` when the charging session was started successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_404_NOT_FOUND` when the Token, Location or EVSE doesn't exist
        * `HTTP_422_UNPROCESSABLE_ENTITY` when the response from CPO is broken
        * `HTTP_424_FAILED_DEPENDENCY` when there is no network connection to the charge point
        """
        try:
            if request.method == 'POST':
                serializer = StartChargingSerializer(data=request.data)
                if serializer.is_valid():
                    evse: Evse = serializer.validated_data['evse']
                    connector_id: str = serializer.validated_data.get('connector_id')
                    contract_id: str = serializer.validated_data.get('contract_id')
                    token = serializer.validated_data['token']
                    if not isinstance(token, Token):
                        token = construct_adhoc_token(token, contract_id)
                    response: requests.Response = send_start_command(request, evse, token, connector_id, contract_id)
                    data = response.json()
                    return Response(data.get('data'), status=response.status_code)
                else:
                    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response(dict(help='Please see `OPTIONS` for the schema'))
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
    def stop_charging(self, request):
        """
        This call stops the charging transaction.

        ## Status codes

        * `HTTP_200_OK` when the charging session was started successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_404_NOT_FOUND` when the Token or the EVSE doesn't exist
        * `HTTP_422_UNPROCESSABLE_ENTITY` when the response from CPO is broken
        """
        try:
            if request.method == 'POST':
                serializer = StopChargingSerializer(data=request.data)
                if serializer.is_valid():
                    token = serializer.validated_data.get('token')
                    session = serializer.validated_data.get('session')

                    response: requests.Response = send_stop_command(request, session)
                    data = response.json()
                    return Response(data.get('data'), status=response.status_code)
                else:
                    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response(dict(help='Please see `OPTIONS` for the schema'))
        except (Evse.DoesNotExist, Token.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)
        except json.JSONDecodeError as e:
            logging.error(f'Cannot process start_transaction response from CPO to eMSP: {e}')
            return Response(
                dict(status=str(e)),
                status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

    # def get_extra_metadata(self, request):
    #     return dict(
    #         start_charging={'return_values': CommandResult.get_fields()},
    #     ).get(self.action_map.get('post'), dict())

    def get_return_values_serializer(self):
        return dict(
            start_charging=CommandResult(),
            stop_charging=CommandResult(),
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
            start_charging=request.build_absolute_uri(
                reverse('roaming-start-charging')
            ),
            stop_charging=request.build_absolute_uri(
                reverse('roaming-stop-charging')
            ),
        )
        return Response(result)

    def get_view_name(self):
        return 'eMobility Service Provider API'


class MSPRouter(routers.DefaultRouter):
    APIRootView = MobilityServiceProviderAPIView
    root_view_name = 'msp-api'
