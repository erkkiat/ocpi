import json
import logging
import os
import uuid
from functools import lru_cache
from typing import Optional, Union

import redis
import requests
from django.conf import settings
from django.utils.module_loading import import_string
from django_filters.rest_framework import DjangoFilterBackend
from icecream import ic
from rest_framework import routers, status, mixins, viewsets, serializers, fields
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.settings import api_settings
from rest_framework.viewsets import GenericViewSet

from ocpi22.choices import OCPP_STATUS_CHOICES, OcppStatusEnum, OcpiRolesEnum
from ocpi22.commands import send_start_command, CommandResult
from ocpi22.location import send_evse_updates
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi_util import AdhocToken
from ocpi22.sessions import create_session
from ocpi22.tokens import authorize_token, get_authorization_from_sessions
from ocpi22.util import HyperlinkedModelSerializerCleanedUp, clear_empty, uid_validator, redis_store
from ocpiconnector import slack_logging

from pprint import PrettyPrinter

from ocpiconnector.ocpi_identities import get_identity, get_our_party

pp = PrettyPrinter(indent=4).pprint
slack_logging.init()


# class EvseSerializer(HyperlinkedModelSerializerCleanedUp):
#     class Meta:
#         model = Evse
#         fields = ['url', 'uid', 'status', 'last_updated']
#
#     uid = serializers.CharField(read_only=True)
#     last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)


# class CpoEvseViewSet(mixins.RetrieveModelMixin,
#                      mixins.UpdateModelMixin,
#                      mixins.DestroyModelMixin,
#                      mixins.ListModelMixin,
#                      GenericViewSet):
#     """
#     This is an optimised subset of the EVSE information available in the OCPI Connector.
#     """
#     filter_backends = [DjangoFilterBackend]
#     filterset_fields = ['status']
#     pagination_class = LimitOffsetPagination
#
#     @staticmethod
#     def put(request, evse_id=None):
#         if not evse_id:
#             evse_id = request.data['uid']
#         # noinspection PyUnresolvedReferences
#         evse = Evse.objects.get(uid=evse_id)
#         serializer = EvseSerializer(evse, data=request.data)
#         if serializer.is_valid():
#             serializer.save()
#             send_evse_updates(evse.uid)
#             return Response(serializer.data)
#         else:
#             return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
#
#     @action(methods=['GET', 'PATCH'], detail=False,
#             url_path='(?P<evse_id>[^/.]+)', url_name='by-id')
#     def evse_by_id(self, request, evse_id) -> Response:
#         """
#         This URL is used for sending charger status updates to the Connector using the PATCH method.
#         Status updates should be real time, so that the eMSPs can show the accurate availability to their customers.
#
#         You can try the status update by changing the status
#         in the input box below and clicking the "PATCH" button.
#
#         See OPTIONS for a detailed API schema.
#
#         """
#         evse = get_object_or_404(Evse, uid=evse_id)
#         # Todo: Handle overlapping EVSE UIDs (how to refer to Evse.location.country_code...)
#
#         if request.method == 'GET':
#             serializer = EvseSerializer(evse, context={'request': request})
#             return Response(serializer.data)
#
#         elif request.method == 'PATCH':
#             serializer = EvseSerializer(evse, data=request.data, partial=True, context={'request': request})
#             if serializer.is_valid():
#                 serializer.save()
#                 send_evse_updates(evse.uid)
#                 return Response(serializer.data)
#             else:
#                 return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
#
#         return Response(status=status.HTTP_400_BAD_REQUEST)
#
#     # noinspection PyUnresolvedReferences
#     queryset = Evse.objects.all().order_by('created')
#     serializer_class = EvseSerializer
#     lookup_field = 'evse_id'


# class CpoSessionSerializer(HyperlinkedModelSerializerCleanedUp):
#     class Meta:
#         model = Session
#         fields = ['session_id', 'billed_to',
#                   'start_date_time', 'end_date_time', 'start_kwh',
#                   'token', 'auth_method', 'authorization_reference',
#                   'location_id', 'evse_uid', 'connector_id', 'currency',
#                   'total_cost_incl_vat', 'total_cost_excl_vat',
#                   'status', 'last_updated']
#
#     session_id = serializers.CharField(source='uid', read_only=True)
#     token = serializers.SerializerMethodField(read_only=True)
#     location_id = serializers.SerializerMethodField(read_only=True)
#     evse_uid = serializers.SerializerMethodField(read_only=True)
#     connector_id = serializers.SerializerMethodField(read_only=True)
#     last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)
#
#     @staticmethod
#     def get_token(session):
#         return clear_empty(dict(
#             token_id=session.cdr_token_uid,
#             type=session.cdr_token_type,
#             contract_id=session.cdr_token_contract_id
#         ))
#
#     @staticmethod
#     def get_location_id(session):
#         return session.location.uid
#
#     @staticmethod
#     def get_evse_uid(session):
#         return session.evse.uid
#
#     @staticmethod
#     def get_connector_id(session):
#         return session.connector.uid


# class ConnectorQuickSerializer(HyperlinkedModelSerializerCleanedUp):
#     class Meta:
#         model = Connector
#         fields = ['uid', 'standard', 'format',
#                   'max_voltage', 'max_amperage', 'max_electric_power',
#                   'tariff_ids', 'last_updated']
#
#     uid = serializers.CharField(validators=[uid_validator])
#     max_electric_power = serializers.SerializerMethodField()
#     tariff_ids = serializers.SerializerMethodField()
#     last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)
#
#     @staticmethod
#     def get_tariff_ids(connector: Connector) -> list:
#         return [t.uid for t in connector.tariff_ids.all()]
#
#     @staticmethod
#     def get_max_electric_power(connector: Connector) -> str:
#         # Todo: what about 1-phase and 2-phase AC?
#         return connector.max_electric_power or connector.max_voltage * connector.max_amperage


# class EvseQuickSerializer(HyperlinkedModelSerializerCleanedUp):
#     class Meta:
#         model = Evse
#         fields = ['status_url', 'uid', 'status', 'connectors', 'last_updated']
#
#     uid = serializers.CharField(validators=[uid_validator])
#     connectors = ConnectorQuickSerializer(many=True)


# class LocationQuickSerializer(HyperlinkedModelSerializerCleanedUp):
#     class Meta:
#         model = Location
#         fields = [
#             'quick_url', 'id',
#             'name', 'address', 'city', 'postal_code', 'state', 'country',
#             'latitude', 'longitude', 'evses',
#         ]
#
#     id = serializers.CharField(source='uid', validators=[uid_validator])
#     evses = EvseQuickSerializer(many=True)
#
#     lookup_field = 'uid'
#
#     # noinspection PyUnresolvedReferences
#     def create(self, validated_data, *args, **kwargs):
#         ic('create', validated_data)
#         evses = validated_data.pop('evses', [])
#         location = Location.objects.create(**validated_data)
#         for evse_dict in evses:
#             connectors = evse_dict.pop('connectors', [])
#             evse = Evse.objects.create(location=location, **evse_dict)
#             for connector_dict in connectors:
#                 Connector.objects.create(evse=evse, **connector_dict)
#         return location
#
#     # noinspection PyUnresolvedReferences
#     def update(self, location, validated_data, *args, **kwargs):
#         ic('update', location, validated_data)
#         evses = validated_data.pop('evses', [])
#         Location.objects.filter(uid=location.uid).update(**validated_data)
#         for evse_dict in evses:
#             connectors = evse_dict.pop('connectors', [])
#             evse, created = Evse.objects.get_or_create(location=location, uid=evse_dict.pop('uid'),
#                                                        defaults=evse_dict)
#             if not created:
#                 Evse.objects.filter(uid=evse.uid).update(**evse_dict)
#             for connector_dict in connectors:
#                 connector, created = Connector.objects.get_or_create(evse=evse,
#                                                                      uid=connector_dict.pop('uid'),
#                                                                      defaults=connector_dict)
#                 if not created:
#                     Connector.objects.filter(uid=connector.uid).update(**connector_dict)
#         return location


# class LocationQuickViewSet(mixins.ListModelMixin,
#                            mixins.UpdateModelMixin,
#                            mixins.RetrieveModelMixin,
#                            GenericViewSet):
#     """
#     This is the endpoint for testing your data format for updating locations.
#     Please note that all IDs should remain constant, since they are referred to by many systems.
#
#     """
#
#     # noinspection PyUnresolvedReferences
#     def put(self, request, uid=None):
#         if uid:
#             our_country_code, our_party_id = Location.get_owner_identity().split('*')
#
#             # Write over an existing Location
#             location: Location = get_object_or_404(Location,
#                                                    uid=uid,
#                                                    country_code=our_country_code,
#                                                    party_id=our_party_id)
#             serializer = self.get_serializer(location, data=request.data)
#         else:
#             # Create a new object
#             # This relies on serializer.create()
#             serializer = self.get_serializer(data=request.data)
#
#         if serializer.is_valid():
#             serializer.save()
#             our_country_code, our_party_id = Location.get_owner_identity().split('*')
#
#             location: Location = get_object_or_404(Location,
#                                                    uid=uid,
#                                                    country_code=our_country_code,
#                                                    party_id=our_party_id)
#             serializer = self.get_serializer(location)
#             ic(serializer.data)
#             return Response(serializer.data)
#         else:
#             return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
#
#     @action(methods=['GET', 'PATCH'], detail=False,
#             url_path='(?P<uid>[^/.]+)')
#     def by_id(self, request, uid) -> Response:
#         # noinspection PyUnresolvedReferences
#         our_country_code, our_party_id = Location.get_owner_identity().split('*')
#
#         location = get_object_or_404(Location, uid=uid,
#                                      country_code=our_country_code,
#                                      party_id=our_party_id)
#
#         if request.method == 'GET':
#             serializer = LocationQuickSerializer(location, context={'request': request})
#             return Response(serializer.data)
#
#         elif request.method == 'PATCH':
#             serializer = LocationQuickSerializer(location, data=request.data, partial=True,
#                                                  context={'request': request})
#             if serializer.is_valid():
#                 serializer.save()
#                 # noinspection PyUnresolvedReferences
#                 serializer = LocationQuickSerializer(Location.objects.get(uid=uid))
#                 return Response(serializer.data)
#             else:
#                 return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
#
#         return Response(status=status.HTTP_400_BAD_REQUEST)
#
#     # noinspection PyUnresolvedReferences
#     queryset = Location.objects.all().order_by('created')
#     serializer_class = LocationQuickSerializer
#     pagination_class = LimitOffsetPagination
#     lookup_field = 'uid'
#
#     @staticmethod
#     def get_object(uid=None) -> Location:
#         # Needed for OPTIONS to work in list view, could just return None
#         if uid:
#             return get_object_or_404(Location, uid=uid)


# class EvseSerializer(fields.CharField):
#     def to_internal_value(self, data):
#         ic(data)
#         return Evse.get_if_exists(uid=data.get('evse_id'), location=data.get('location_id'))
#
#
# class LocationSerializer(fields.CharField):
#     def to_internal_value(self, location_id):
#         return Location.get_if_exists(uid=location_id)


class TokenIdSerializer(fields.CharField):
    def to_internal_value(self, data):
        token = Token.get_if_exists(uid=data) or data
        return token


class StartChargingSerializer(serializers.Serializer):
    location_id = serializers.CharField(
        # source="*",
        max_length=36
    )
    evse_id = serializers.CharField(
        # source='*',
        help_text='The identifier of the device which provides electricity to one or more connectors'
    )
    connector_id = serializers.CharField(
        required=False,
        max_length=36,
        help_text='The connector number used for charging during this transaction'
    )
    token_id = TokenIdSerializer(
        source='token',
        help_text='The hidden ID of the RFID token, separate from the visual one'
    )

    def to_internal_value(self, data):
        evse_id = self.initial_data.get('evse_id')
        location_id = self.initial_data.get('location_id')
        location = Location.get_if_exists(uid=location_id)
        evse = Evse.get_if_exists(uid=evse_id, location=location)
        if not evse:
            raise ValidationError(
                {api_settings.NON_FIELD_ERRORS_KEY: [f'EVSE with ID {evse_id} at location {location_id} not found']}
            )
        data = super().to_internal_value(data)
        data['evse'] = evse
        return data


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
        """
        try:
            if request.method == 'POST':
                serializer = StartChargingSerializer(data=request.data)
                if serializer.is_valid():
                    evse: Evse = serializer.validated_data['evse']
                    connector_id: str = serializer.validated_data['connector_id']
                    token = serializer.validated_data['token']

                    response: requests.Response = send_start_command(request, evse, token)
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
                serializer = StartChargingSerializer(data=request.data)
                if serializer.is_valid():
                    evse: Evse = serializer.validated_data['evse']
                    connector_id: str = serializer.validated_data['connector_id']
                    token = serializer.validated_data['token']

                    response: requests.Response = send_start_command(request, evse, token)
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
