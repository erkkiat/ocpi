import logging
import os
import uuid
from functools import lru_cache
from typing import Optional, Union

import redis
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
from rest_framework.viewsets import GenericViewSet

from ocpi22.choices import OCPP_STATUS_CHOICES, OcppStatusEnum, OcpiRolesEnum
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


class EvseSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Evse
        fields = ['url', 'uid', 'status', 'last_updated']

    uid = serializers.CharField(read_only=True)
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)


class CpoEvseViewSet(mixins.RetrieveModelMixin,
                     mixins.UpdateModelMixin,
                     mixins.DestroyModelMixin,
                     mixins.ListModelMixin,
                     GenericViewSet):
    """
    This is an optimised subset of the EVSE information available in the OCPI Connector.
    """
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status']
    pagination_class = LimitOffsetPagination

    @staticmethod
    def put(request, evse_id=None):
        if not evse_id:
            evse_id = request.data['uid']
        # noinspection PyUnresolvedReferences
        evse = Evse.objects.get(uid=evse_id)
        serializer = EvseSerializer(evse, data=request.data)
        if serializer.is_valid():
            serializer.save()
            send_evse_updates(evse.uid)
            return Response(serializer.data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=['GET', 'PATCH'], detail=False,
            url_path='(?P<evse_id>[^/.]+)', url_name='by-id')
    def evse_by_id(self, request, evse_id) -> Response:
        """
        This URL is used for sending charger status updates to the Connector using the PATCH method.
        Status updates should be real time, so that the eMSPs can show the accurate availability to their customers.

        You can try the status update by changing the status
        in the input box below and clicking the "PATCH" button.

        See OPTIONS for a detailed API schema.

        """
        evse = get_object_or_404(Evse, uid=evse_id)
        # Todo: Handle overlapping EVSE UIDs (how to refer to Evse.location.country_code...)

        if request.method == 'GET':
            serializer = EvseSerializer(evse, context={'request': request})
            return Response(serializer.data)

        elif request.method == 'PATCH':
            serializer = EvseSerializer(evse, data=request.data, partial=True, context={'request': request})
            if serializer.is_valid():
                serializer.save()
                send_evse_updates(evse.uid)
                return Response(serializer.data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_400_BAD_REQUEST)

    # noinspection PyUnresolvedReferences
    queryset = Evse.objects.all().order_by('created')
    serializer_class = EvseSerializer
    lookup_field = 'evse_id'


class CpoSessionSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Session
        fields = ['session_id', 'billed_to',
                  'start_date_time', 'end_date_time', 'start_kwh',
                  'token', 'auth_method', 'authorization_reference',
                  'location_id', 'evse_uid', 'connector_id', 'currency',
                  'total_cost_incl_vat', 'total_cost_excl_vat',
                  'status', 'last_updated']

    session_id = serializers.CharField(source='uid', read_only=True)
    token = serializers.SerializerMethodField(read_only=True)
    location_id = serializers.SerializerMethodField(read_only=True)
    evse_uid = serializers.SerializerMethodField(read_only=True)
    connector_id = serializers.SerializerMethodField(read_only=True)
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)

    @staticmethod
    def get_token(session):
        return clear_empty(dict(
            token_id=session.cdr_token_uid,
            type=session.cdr_token_type,
            contract_id=session.cdr_token_contract_id
        ))

    @staticmethod
    def get_location_id(session):
        return session.location.uid

    @staticmethod
    def get_evse_uid(session):
        return session.evse.uid

    @staticmethod
    def get_connector_id(session):
        return session.connector.uid


class ConnectorQuickSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Connector
        fields = ['uid', 'standard', 'format',
                  'max_voltage', 'max_amperage', 'max_electric_power',
                  'tariff_ids', 'last_updated']

    uid = serializers.CharField(validators=[uid_validator])
    max_electric_power = serializers.SerializerMethodField()
    tariff_ids = serializers.SerializerMethodField()
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)

    @staticmethod
    def get_tariff_ids(connector: Connector) -> list:
        return [t.uid for t in connector.tariff_ids.all()]

    @staticmethod
    def get_max_electric_power(connector: Connector) -> str:
        # Todo: what about 1-phase and 2-phase AC?
        return connector.max_electric_power or connector.max_voltage * connector.max_amperage


class EvseQuickSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Evse
        fields = ['status_url', 'uid', 'status', 'connectors', 'last_updated']

    uid = serializers.CharField(validators=[uid_validator])
    connectors = ConnectorQuickSerializer(many=True)


class LocationQuickSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Location
        fields = [
            'quick_url', 'id',
            'name', 'address', 'city', 'postal_code', 'state', 'country',
            'latitude', 'longitude', 'evses',
        ]

    id = serializers.CharField(source='uid', validators=[uid_validator])
    evses = EvseQuickSerializer(many=True)

    lookup_field = 'uid'

    # noinspection PyUnresolvedReferences
    def create(self, validated_data, *args, **kwargs):
        ic('create', validated_data)
        evses = validated_data.pop('evses', [])
        location = Location.objects.create(**validated_data)
        for evse_dict in evses:
            connectors = evse_dict.pop('connectors', [])
            evse = Evse.objects.create(location=location, **evse_dict)
            for connector_dict in connectors:
                Connector.objects.create(evse=evse, **connector_dict)
        return location

    # noinspection PyUnresolvedReferences
    def update(self, location, validated_data, *args, **kwargs):
        ic('update', location, validated_data)
        evses = validated_data.pop('evses', [])
        Location.objects.filter(uid=location.uid).update(**validated_data)
        for evse_dict in evses:
            connectors = evse_dict.pop('connectors', [])
            evse, created = Evse.objects.get_or_create(location=location, uid=evse_dict.pop('uid'),
                                                       defaults=evse_dict)
            if not created:
                Evse.objects.filter(uid=evse.uid).update(**evse_dict)
            for connector_dict in connectors:
                connector, created = Connector.objects.get_or_create(evse=evse,
                                                                     uid=connector_dict.pop('uid'),
                                                                     defaults=connector_dict)
                if not created:
                    Connector.objects.filter(uid=connector.uid).update(**connector_dict)
        return location


class LocationQuickViewSet(mixins.ListModelMixin,
                           mixins.UpdateModelMixin,
                           mixins.RetrieveModelMixin,
                           GenericViewSet):
    """
    This is the endpoint for testing your data format for updating locations.
    Please note that all IDs should remain constant, since they are referred to by many systems.

    """

    # noinspection PyUnresolvedReferences
    def put(self, request, uid=None):
        if uid:
            our_country_code, our_party_id = Location.get_owner_identity().split('*')

            # Write over an existing Location
            location: Location = get_object_or_404(Location,
                                                   uid=uid,
                                                   country_code=our_country_code,
                                                   party_id=our_party_id)
            serializer = self.get_serializer(location, data=request.data)
        else:
            # Create a new object
            # This relies on serializer.create()
            serializer = self.get_serializer(data=request.data)

        if serializer.is_valid():
            serializer.save()
            our_country_code, our_party_id = Location.get_owner_identity().split('*')

            location: Location = get_object_or_404(Location,
                                                   uid=uid,
                                                   country_code=our_country_code,
                                                   party_id=our_party_id)
            serializer = self.get_serializer(location)
            ic(serializer.data)
            return Response(serializer.data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=['GET', 'PATCH'], detail=False,
            url_path='(?P<uid>[^/.]+)')
    def by_id(self, request, uid) -> Response:
        # noinspection PyUnresolvedReferences
        our_country_code, our_party_id = Location.get_owner_identity().split('*')

        location = get_object_or_404(Location, uid=uid,
                                     country_code=our_country_code,
                                     party_id=our_party_id)

        if request.method == 'GET':
            serializer = LocationQuickSerializer(location, context={'request': request})
            return Response(serializer.data)

        elif request.method == 'PATCH':
            serializer = LocationQuickSerializer(location, data=request.data, partial=True,
                                                 context={'request': request})
            if serializer.is_valid():
                serializer.save()
                # noinspection PyUnresolvedReferences
                serializer = LocationQuickSerializer(Location.objects.get(uid=uid))
                return Response(serializer.data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_400_BAD_REQUEST)

    # noinspection PyUnresolvedReferences
    queryset = Location.objects.all().order_by('created')
    serializer_class = LocationQuickSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = 'uid'

    @staticmethod
    def get_object(uid=None) -> Location:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Location, uid=uid)


def _find_our_evse(evse_uid) -> Evse:
    party = get_our_party(OcpiRolesEnum.CPO)
    evses = Evse.objects.filter(uid=evse_uid).select_related('location'). \
        filter(location__country_code=party.country_code, location__party_id=party.party_id)
    evse_count = evses.count()
    if not evse_count:
        raise Evse.DoesNotExist(f'EVSE with ID {evse_uid} '
                                f'does not exist in the OCPI Connector database for party {str(party)}')
    if evse_count > 1:
        raise Evse.DoesNotExist(f'There are more than one EVSE with ID {evse_uid} '
                                f'in the OCPI Connector database for party {str(party)}')
    return evses.first()


class EvseSerialnumberSerializer(fields.CharField):
    def to_internal_value(self, evse_uid):
        return _find_our_evse(evse_uid)


class TokenIdSerializer(fields.CharField):
    def to_internal_value(self, data):
        token = Token.get_if_exists(uid=data) or data
        return token


class SessionIdSerializer(fields.CharField):
    def to_internal_value(self, data):
        return Session.objects.get(uid=data)


class OcppStatusSerializer(fields.ChoiceField):
    def __init__(self):
        super().__init__(OCPP_STATUS_CHOICES)

    def to_internal_value(self, data):
        result = {
            OcppStatusEnum.AVAILABLE.value: 'AVAILABLE',
            OcppStatusEnum.PREPARING.value: 'CHARGING',
            OcppStatusEnum.CHARGING.value: 'CHARGING',
            OcppStatusEnum.SUSPENDEDEV.value: 'CHARGING',
            OcppStatusEnum.SUSPENDEDEVSE.value: 'CHARGING',
            OcppStatusEnum.FINISHING.value: 'CHARGING',
            OcppStatusEnum.RESERVED.value: 'RESERVED',
            OcppStatusEnum.UNAVAILABLE.value: 'CHARGING',
            OcppStatusEnum.FAULTED.value: 'OUTOFORDER',
        }.get(data.upper())
        if not result:
            options = [x[0] for x in OCPP_STATUS_CHOICES]
            raise ValidationError(f"'{data}' is not a known OCPP status. Options are: {options}.")
        return result


class StatusChangeSerializer(serializers.Serializer):
    evse_id = EvseSerialnumberSerializer(
        source='evse',
        help_text='The identifier of the device which provides electricity to one or more connectors'
    )
    status = OcppStatusSerializer()


class AuthorizationSerializer(serializers.Serializer):
    evse_id = EvseSerialnumberSerializer(
        source='evse',
        help_text='The identifier of the device which provides electricity to one or more connectors'
    )
    token_id = TokenIdSerializer(
        source='token',
        help_text='The hidden ID of the RFID token, separate from the visual one'
    )


class MeterValuesSerializer(serializers.Serializer):
    """
    The session start and end time are recorded by the OCPI Connector
    """
    session_id = SessionIdSerializer(
        source='session',
        help_text='The session ID on the CPO platform or order number from the billing system',
    )
    kwh = serializers.FloatField(
        help_text='The kWh measurement at the time of this message',
    )


class StartTransactionSerializer(serializers.Serializer):
    evse_id = EvseSerialnumberSerializer(
        source='evse',
        help_text='The identifier of the device which provides electricity to one or more connectors'
    )
    connector_id = serializers.CharField(
        max_length=36,
        help_text='The connector number used for charging during this transaction'
    )
    token_id = TokenIdSerializer(
        source='token',
        help_text='The hidden ID of the RFID token, separate from the visual one'
    )
    session_id = serializers.CharField(
        max_length=36,
        help_text='The session ID on the CPO platform or order number from the billing system',
        required=False,
        default=uuid.uuid4().hex
    )
    start_kwh = serializers.FloatField(
        help_text='The kWh measurement at the meter at start of the transaction, can start from zero '
                  'or start from where the previous charging session ended or some other value'
    )


class StopTransactionSerializer(serializers.Serializer):
    """
    The session ends with a specific meter value
    """
    session_id = SessionIdSerializer(
        source='session',
        help_text='The session ID on the CPO platform or order number from the billing system',
    )
    stop_kwh = serializers.FloatField(
        help_text='The kWh measurement when the charging session ends',
    )


class CallbacksSerializer(serializers.Serializer):
    """
    The URLs for callback endpoints in the CPO system
    """
    START_TRANSACTION_URL = 'start_transaction_url'
    STOP_TRANSACTION_URL = 'stop_transaction_url'

    start_transaction_url = serializers.URLField()
    stop_transaction_url = serializers.URLField()
    # unlock_connector_url = serializers.URLField(required=False)
    # reserve_now_url = serializers.URLField(required=False)
    # cancel_reservation_url = serializers.URLField(required=False)
    user = serializers.CharField(allow_blank=True, allow_null=True)
    password = serializers.CharField(write_only=True, allow_blank=True, allow_null=True)

    def save(self):
        for key, value in self.validated_data.items():
            set_callbacks_parameter(key, value)
        # redis_store.save()  # This is not allowed in Heroku Redis


def _format_redis_key(key: str, namespace: str) -> str:
    return f'{namespace}-{key}'


def set_callbacks_parameter(key: str, value: str) -> None:
    redis_store.set(_format_redis_key(key, 'callback'), value)


@lru_cache(maxsize=128)
def get_callbacks_parameter(key: str) -> Union[str, int, list]:
    return redis_store.get(_format_redis_key(key, 'callback'))


# Todo: limit access to certain privilege holders
class ChargePointViewSet(viewsets.GenericViewSet):
    """
    The charge point is connected to roaming networks through this API. It interprets the OCPP
    status and other data from the charge point.
    """

    # noinspection PyUnresolvedReferences
    queryset = Location.objects.all()  # Todo: Just in case, show only our Locations
    lookup_field = 'uid'

    def get_serializer_class(self):
        return dict(
            authorize=AuthorizationSerializer,
            status_change=StatusChangeSerializer,
            start_transaction=StartTransactionSerializer,
            meter_values=MeterValuesSerializer,
            stop_transaction=StopTransactionSerializer,
            callbacks=CallbacksSerializer,
        ).get(self.action_map.get('post'), StatusChangeSerializer)

    @action(methods=('GET', 'POST'), detail=False)
    def status_change(self, request):
        """
        Update the charge point availability to the roaming network parties.

        **IMPORTANT**: To prevent the EV battery from running out, please update the status
        whenever your monitoring notices a possible problem with the charge point. This way
        we will be able to show the real availability status to the driver.

        ## Status codes

        * `HTTP_200_OK` when the EVSE status has been successfully updated
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_404_NOT_FOUND` when the EVSE or Token is not found

        """
        try:
            if request.method == 'POST':
                serializer = StatusChangeSerializer(data=request.data)
                if serializer.is_valid():
                    ocpp_status = serializer.initial_data.get('status')
                    ocpi_status = serializer.validated_data.get('status')

                    # Todo: Filter just our evses
                    evse: Evse = serializer.validated_data.get('evse')

                    evse.status = ocpi_status
                    evse.save()
                    return Response(
                        dict(
                            status_text=f'EVSE status has been changed',
                            evse=evse.uid,
                            ocpi_status=evse.status,
                            ocpp_status=ocpp_status
                        )
                    )
                else:
                    return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response(dict(help='Please see `OPTIONS` for the schema'))
        except (Evse.DoesNotExist, Token.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)

    @action(methods=('GET', 'POST'), detail=False)
    def authorize(self, request):
        """
        Authorize charging using a specific RFID token. This API call is not mandatory for starting a
        charging session. `Start_transaction` will request authorization from MSP if needed.

        **NOTE**: Authorization responses are cached for 15 minutes, so feel free to
        call this endpoint multiple times when preparing to start a charging session.

        ## Status codes

        * `HTTP_200_OK` when the RFID tag was authorized for charging
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_401_UNAUTHORIZED` when the RFID tag exists, but is not valid for charging at the moment
        * `HTTP_404_NOT_FOUND` when the RFID tag does not exist
        """
        try:
            if request.method == 'POST':
                serializer = AuthorizationSerializer(data=request.data)
                if serializer.is_valid():
                    evse: Evse = serializer.validated_data.get('evse')
                    token: Token = serializer.validated_data.get('token')
                    if isinstance(token, str):
                        # This is an AD_HOC_USER or APP_USER Token, no authorization request allowed by OCPI
                        authorization_method, authorization_reference, party, token_type = get_authorization_from_sessions(
                            token)
                        # eMSP has already authorized this token for 15 minutes
                        token = AdhocToken(uid=token, valid=True, owner=party, type=token_type)
                    else:
                        authorization_method, authorization_reference = authorize_token(token, evse.location)
                    if not authorization_method or not token.valid:
                        return Response(
                            dict(status=f'Token `{token}` is (temporarily) not valid'),
                            status=status.HTTP_401_UNAUTHORIZED
                        )

                    return Response(
                        dict(
                            status_text=f'Token authorized for charging',
                            evse=evse.uid,
                            token=str(token),
                            billed_to=token.party(),
                            authorization_reference=authorization_reference,
                            authorization_method=authorization_method
                        )
                    )
                else:
                    return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response(dict(help='Please see `OPTIONS` for the schema'))
        except (Evse.DoesNotExist, Token.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)

    @action(methods=('GET', 'POST'), detail=False)
    def start_transaction(self, request):
        """
        This call starts the charging transaction (which equals the OCPI session in the roaming network).

        **ENERGY**: If your charge point doesn't reset its energy meter between charging sessions,
        set start_kwh to the current meter value at the start of the session.

        **AUTHORIZATION REQUEST**: You don't have to call the `authorization` endpoint before `start_transaction`,
        since we will call it for you. Also, authorization requests are not sent to MSP when the
        Token has `whitelist=ALWAYS`, and in such cases **authorization_reference will be an empty string**.

        **CHARGER STATUS**: Please update the status to `CHARGING` by using `status_change`.
        The session will be started regardless of charger status,
        in case some status change messages have been lost on the way.

        ## Status codes

        * `HTTP_200_OK` when the charging session was started successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_404_NOT_FOUND` when the Token or the EVSE doesn't exist
        * `HTTP_409_CONFLICT` when a Session with the same session_id already exists
        """
        try:
            if request.method == 'POST':
                serializer = StartTransactionSerializer(data=request.data)
                if serializer.is_valid():
                    evse: Evse = serializer.validated_data['evse']
                    connector_id: str = serializer.validated_data['connector_id']
                    session_id = serializer.validated_data['session_id']
                    token = serializer.validated_data['token']
                    start_kwh = serializer.validated_data['start_kwh']

                    if Session.objects.filter(uid=session_id).exists():
                        return Response(
                            dict(
                                status_text=f'Session {session_id} already exists',
                            ),
                            status=status.HTTP_409_CONFLICT,
                        )
                    # Todo: Session.currency needs to match with Tariff currency
                    session = create_session(
                        # Todo: Make sure overlapping evse.uid is not a problem for CPO + eMSP role
                        # Other CPO can have same ID
                        uid=session_id, evse_id=evse, location_id=evse.location, connector_id=connector_id,
                        token_id=token, billed_to=token.party(), start_kwh=start_kwh, stop_kwh=start_kwh,
                        session_status=Session.ACTIVE
                    )
                    session_serializer = CpoSessionSerializer(instance=session)
                    return Response(
                        dict(
                            status_text=f'Session started',
                            # session_id=session_id,
                            # billed_to=token.party(),
                            # start_kwh=start_kwh,
                            # authorization_method=session.auth_method,
                            # authorization_reference=session.authorization_reference,
                            session=session_serializer.data,
                        )
                    )
                else:
                    return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response(dict(help='Please see `OPTIONS` for the schema'))
        except (Evse.DoesNotExist, Token.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)

    @action(methods=('GET', 'POST'), detail=False)
    def meter_values(self, request):
        """
        Update the session progress. This endpoint should be called at least once per minute with the
        up to date information about the ongoing charging session.

        ## Status codes

        * `HTTP_200_OK` when the session was updated with the provided meter values
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_404_NOT_FOUND` when the Session doesn't exist
        * `HTTP_417_EXPECTATION_FAILED` when the applicable Tariff is misconfigured

        ## Energy

        The used energy is calculated by `kwh - start_kwh` (given in `start_transaction`).

        """
        try:
            if request.method == 'POST':
                serializer = MeterValuesSerializer(data=request.data)
                if serializer.is_valid():
                    session = serializer.validated_data['session']
                    kwh = serializer.validated_data['kwh']
                    session.stop_kwh = kwh
                    session.save(update_fields=['stop_kwh'])
                    session.calculate_price()
                    session.send_updates()  # Todo: send only to billed_to

                    return Response(
                        dict(
                            status_text=f'Session updated',
                            session_id=session.uid,
                            start_kwh=session.start_kwh,
                            now_kwh=kwh,
                            total_kwh=session.kwh,
                            price=session.cost(),
                        )
                    )
                else:
                    return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response(dict(help='Please see `OPTIONS` for the schema'))
        except (Evse.DoesNotExist, Token.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)
        except ValidationError as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_417_EXPECTATION_FAILED)

    @action(methods=('GET', 'POST'), detail=False)
    def stop_transaction(self, request):
        """
        End the transaction, charging session has been finished.

        **ENERGY**: The used energy is calculated by `stop_kwh - start_kwh`
        (`start_kwh` was given in `start_transaction`).

        **CHARGER STATUS**: Please update the status by using `status_change`.

        ## Status codes

        * `HTTP_200_OK` when the session was finished and Charge Detail Record was created successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_404_NOT_FOUND` when the Session doesn't exist
        """
        try:
            if request.method == 'POST':
                serializer = StopTransactionSerializer(data=request.data)
                if serializer.is_valid():
                    session = serializer.validated_data['session']
                    stop_kwh = serializer.validated_data['stop_kwh']
                    session.stop_kwh = stop_kwh
                    session.status = Session.COMPLETED
                    session.save(update_fields=['stop_kwh', 'status'])
                    session.calculate_price()

                    # Create the corresponding CDR (it will also be sent to other party)
                    from ocpi22.models.cdr import Cdr
                    from ocpi22.api import CdrSerializer
                    cdr = Cdr.create_based_on_session(session)
                    cdr.save()

                    cdr_json = CdrSerializer(instance=cdr)
                    session_serializer = CpoSessionSerializer(instance=session)

                    return Response(
                        dict(
                            status_text=f'Session finished',
                            session_id=session.uid,
                            kwh_total=session.kwh,
                            session=session_serializer.data,
                            charge_detail_record=cdr_json.data
                        )
                    )
                else:
                    return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response(dict(help='Please see `OPTIONS` for the schema'))
        except (Evse.DoesNotExist, Token.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)

    def _get_callbacks(self):
        serializer = CallbacksSerializer()
        data = dict(
            [(key, get_callbacks_parameter(key)) for key in serializer.fields.keys()]
        )
        serializer = CallbacksSerializer(instance=data)
        return serializer.data

    @action(methods=('GET', 'POST', 'PATCH'), detail=False)
    def callbacks(self, request):
        """
        You need to tell the OCPI Connector where to send commands such as `start transaction` and
        `stop transaction`. Using this endpoint you can set and get your callback URLs and
        user credentials needed for accessing the endpoints you specify. When you GET the
        settings, `password` will never be shown.

        **NOTE**: To clear `user` or `password`, set them to an empty string.

        ## Status codes

        * `HTTP_200_OK` when the session was finished and Charge Detail Record was created successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way

        """
        try:
            if request.method == 'GET':
                return Response(self._get_callbacks())
            if request.method in ('POST', 'PATCH'):
                partial = bool(request.method == 'PATCH')
                serializer = CallbacksSerializer(data=request.data, partial=partial)
                if serializer.is_valid():
                    serializer.save()
                    get_callbacks_parameter.cache_clear()
                    return Response(self._get_callbacks())
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except redis.exceptions.ConnectionError as e:
            logging.error(f'{settings.HOSTNAME}: Cannot read and store callback settings  '
                          f'due to trouble connecting with Redis: {e}')
            return Response(
                dict(
                    status_text='Unable to store settings due to connection problem with Redis. '
                                'This is our fault, sorry. Support has been alerted.'
                ),
                status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(f'{request.method} is not supported', status=status.HTTP_400_BAD_REQUEST)

    def get_view_name(self):
        if self.name:
            return f'{self.name.capitalize()}'
        return f'Status Change'

    @staticmethod
    def get_object(uid=None) -> None:
        # Needed for OPTIONS to work in list view
        return None


class ChargePointOperatorAPIView(routers.APIRootView):
    """
    This API is not a part of the OCPI protocol. It is intended as fast shortcut to OCPI roaming.

    > Here you can use the CPO API interfaces intearactively
    > to support your development and integration work.
    > These streamlined interfaces provide the necessary tools for quickly but comprehensively connecting
    > a CPO backend to eMSPs and hubs using the OCPI protocol.

    **ADMIN UI**: All the objects in the OCPI Connector are available for browsing
    and selective modification in the admin tools.
    It also provides tools for maintaining users, groups and their access to the OCPI Connector.

    For more details, click the examples below and you will find the step-by-step technical documentation.

    """

    # noinspection PyUnresolvedReferences
    def get(self, request, *args, **kwargs):
        """
        Compile the example URLs for the root page
        """

        result = dict(
            status_change=request.build_absolute_uri(
                reverse('chargepoint-status-change')
            ),
            authorize=request.build_absolute_uri(
                reverse('chargepoint-authorize')
            ),
            start_transaction=request.build_absolute_uri(
                reverse('chargepoint-start-transaction')
            ),
            meter_values=request.build_absolute_uri(
                reverse('chargepoint-meter-values')
            ),
            stop_transaction=request.build_absolute_uri(
                reverse('chargepoint-stop-transaction')
            ),
            callbacks=request.build_absolute_uri(
                reverse('chargepoint-callbacks')
            ),
        )
        return Response(result)

    def get_view_name(self):
        return 'Charge Point Operator API'


class CPORouter(routers.DefaultRouter):
    APIRootView = ChargePointOperatorAPIView
    root_view_name = 'cpo-api'


class Charger:
    AUTHORIZATION_CHOICES = (
        ('Accepted', 'Accepted'),
        ('Blocked', 'Blocked'),
        ('Expired', 'Expired'),
        ('Invalid', 'Invalid'),
        ('ConcurrentTx', 'ConcurrentTx'),
    )

    class UnlockStatus:
        value = None

        def __int__(self, value):
            assert value in ('Unlocked', 'UnlockFailed', 'NotSupported')
            self.value = value

        def __str__(self):
            return self.value

    @staticmethod
    def remote_start_transaction(token: str, evse: Evse) -> Optional[str]:
        """
        Start a charging session

        @param session:
        @return: Connector ID
        """
        # ic()
        # ic(token, evse)
        # noinspection PyUnresolvedReferences
        connectors = evse.connectors.all()
        if connectors.count(): return connectors[0]
        return None

    @staticmethod
    def remote_stop_transaction(session: Session) -> bool:
        # ic()
        # ic(session)
        return True

    @staticmethod
    def unlock_connector(location_id, evse_uid, connector_id, **kwargs) -> bool:
        # ic()
        # ic(location_id, evse_uid, connector_id, kwargs)
        return True

    @staticmethod
    def add_or_update_token(id_token: str, validity: bool, created=None) -> bool:
        """
        Send a new or changed token to charge point

        @param id_token: Token UID
        @param validity: Is the token valid for use or not
        @return: True, if the token was updated
        """
        # ic()
        # ic(id_token, validity, created)
        return True


charger_class = os.environ.get('CHARGER_CLASS', 'ocpi22.cpo_api.Charger')
CHARGER = import_string(charger_class)
