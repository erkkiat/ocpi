import os
import uuid
from typing import Optional

from django.utils import timezone
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

from ocpi22.choices import OCPP_STATUS_CHOICES, OcppStatusEnum
from ocpi22.location import send_evse_updates
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.sessions import create_session
from ocpi22.tokens import authorize_token
from ocpi22.util import HyperlinkedModelSerializerCleanedUp, clear_empty, uid_validator
from ocpiconnector import slack_logging

from pprint import PrettyPrinter

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


class SessionSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Session
        fields = ['url', 'uid',
                  'start_date_time', 'end_date_time', 'kwh',
                  'token', 'auth_method', 'authorization_reference',
                  'location_id', 'evse_uid', 'connector_id', 'currency',
                  'total_cost_incl_vat', 'total_cost_excl_vat',
                  'status', 'last_updated']

    uid = serializers.CharField(read_only=True)
    token = serializers.SerializerMethodField(read_only=True)
    location_id = serializers.SerializerMethodField(read_only=True)
    evse_uid = serializers.SerializerMethodField(read_only=True)
    connector_id = serializers.SerializerMethodField(read_only=True)
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)

    @staticmethod
    def get_token(session):
        return clear_empty(dict(
            uid=session.cdr_token_uid,
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


# class SessionViewSet(viewsets.ViewSet):
#     """
#     Congratulations, you have started a session!
#
#     This step should happen when the driver starts charging using an RFID at the charge point.
#     The first step is that the CPO sends a "start session" GET to the below URL.
#
#     * The start session URL: GET /api/cpo/v1/session/start/{evse_id}/{connector_id}/{token_id}/
#
#     If the response contains a "incomplete_sessions_invalidated" node, that means that there was a session in progress
#     at this specific EVSE. That session was invalidated, although your response shows the EVSE's earlier status.
#
#     """
#     # noinspection PyUnresolvedReferences
#     queryset = Session.objects.all().order_by('created')
#     pagination_class = LimitOffsetPagination
#
#     @action(methods=['PATCH'], detail=False, url_name='update',
#             url_path='update/(?P<session_id>[^/.]+)')
#     def update_session(self, request, session_id) -> Response:
#         """
#         After the session has been started, it is recommended to send an update with each kWh consumed,
#         so that the driver can monitor the progress of
#         the charging session. This is done by sending a PATCH to this URL, for example { "kwh": 10 }. You can
#         try it in the input box below.
#
#         * To update a session, send a PATCH to /api/cpo/v1/session/update/{session_id}/
#         with a body containing the updated fields in JSON format
#
#         * Finally, to finish the session, send the last update and then a GET to /api/cpo/v1/session/finish/{session_id}/
#         """
#         pp(f'*** OCPI Connector got an update from CPO/charger for session {session_id}: {request.data}')
#         session = get_object_or_404(Session, uid=session_id)
#         if session.is_final():
#             return Response(dict(error='This session cannot be updated, since it already has a final status'),
#                             status.HTTP_401_UNAUTHORIZED)
#         serializer = SessionSerializer(session, data=request.data, partial=True, context={'request': request})
#         if serializer.is_valid():
#             if serializer.validated_data['kwh']:
#                 serializer.validated_data['status'] = 'ACTIVE'
#
#             # Let's not try to calculate all costs before the end of the Session
#             # end_date_time = session.end_date_time or timezone.now()
#             # serializer.validated_data['total_cost_incl_vat'], \
#             #     serializer.validated_data['total_cost_excl_vat'] = \
#             #     self.calculate_price(session.connector, session.kwh,
#             #                          (end_date_time - session.start_date_time).seconds / 60 / 60)
#
#             serializer.save()
#             # Todo: send update to MSP
#             result = dict(finish_url=request.build_absolute_uri(reverse('session-finish', args=[session.uid])))
#             result.update(serializer.data)
#             return Response(result)
#         else:
#             return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
#
#     @action(methods=['GET'], detail=False, url_name='finish',
#             url_path='finish/(?P<session_id>[^/.]+)')
#     def finish_session(self, request, session_id) -> Response:
#         """
#         The finish session endpoint closes the specified session regardless of its status.
#         The status of a finished session is "COMPLETED", or in case kwh is 0.0, the session status will be "INVALID".
#
#         In case this EVSE has one or more unfinished sessions left hanging,
#         the response will have a list called "incomplete_sessions_invalidated",
#         which shows the sessions which were discarded by changing their status to "INVALID". These sessions will not
#         be billed, but they can still be found in the admin tools.
#         """
#         session = get_object_or_404(Session, uid=session_id)
#         if session.is_final():
#             return Response(dict(error='This session cannot be finished, since it already has a final status'),
#                             status.HTTP_401_UNAUTHORIZED)
#
#         if session.status == Session.PENDING and not session.kwh:
#             session.status = Session.INVALID
#         elif session.status != Session.ACTIVE and session.kwh:
#             return Response(dict(
#                 error=f'Session {session_id} was already finished. {session}'
#             ))
#         else:
#             session.status = Session.COMPLETED
#         session.end_date_time = timezone.now()
#         session.calculate_price()
#         session.save()
#         result = dict(session=SessionSerializer(session, context={'request': request}).data)
#         if session.kwh:
#             # noinspection PyUnresolvedReferences
#             cdr: Cdr = Cdr.create_based_on_session(session)
#             from ocpi22.api import CdrSerializer
#             result['cdr'] = CdrSerializer(cdr, context={'request': request}).data
#
#             # from ocpi22.commands import sh
#             # logging.basicConfig(handlers=[sh], level=logging.INFO)
#             logging.info(f'Successful charging session finished at {session.location}, EVSE: {session.evse.evse_id}, '
#                          f'kwh: {session.kwh}, total time: {cdr.total_time * 60:.0f} minutes, '
#                          f'cost: {session.total_cost_incl_vat} {session.currency}', extra={'notify_slack': True})
#
#         return Response(result)
#
#     @transaction.atomic
#     @action(methods=['GET'], detail=False, url_name='start',
#             url_path='start/(?P<evse_id>[^/.]+)/(?P<connector_id>[^/.]+)/(?P<token_uid>[^/.]+)')
#     def start_session(self, request, evse_id, connector_id, token_uid) -> Response:
#         evse = get_object_or_404(Evse, uid=evse_id)
#         location = evse.location
#         connector = get_object_or_404(Connector, uid=connector_id, evse=evse)
#         auth_method, authorization_info = authorize_token(token_uid, location)
#         if not auth_method:
#             return Response(dict(error=f'Token {token_uid} was not authorized for use by MSP at this time'),
#                             status=status.HTTP_401_UNAUTHORIZED)
#         if not authorization_info:
#             text = f'There is technical error authorizing {token_uid}, response from MSP is missing token information.'
#             logging.error(text)
#             return Response(dict(error=text))
#         token = authorization_info.get('token')
#         # noinspection PyUnresolvedReferences
#         active_session = Session.objects.filter(evse=evse, status__in=('ACTIVE', 'PENDING'))
#         if active_session.count():
#             logging.warning('Starting a new session while one or more previous sessions have not been finished. '
#                             f'Invalidating incomplete sessions: {",".join([str(s) for s in active_session])}')
#             active_session.update(status='INVALID')
#
#         # noinspection PyUnresolvedReferences
#         session = Session.objects.create(
#             country_code='FI',
#             party_id=os.environ.get('CPO_PARTY_ID', 'EKI'),
#             uid=uuid.uuid4().hex,
#             kwh=0.0,
#             start_date_time=timezone.now(),
#             cdr_token_uid=token.get('uid'),
#             cdr_token_type=token.get('type'),
#             cdr_token_contract_id=token.get('contract_id'),
#             auth_method=auth_method,
#             authorization_reference=authorization_info.get('authorization_reference'),
#             location=location,
#             evse=evse,
#             connector=connector,
#             currency=os.environ.get('CPO_CURRENCY', 'EUR')
#         )
#
#         result = dict(
#             update_url=request.build_absolute_uri(reverse('session-update', args=[session.uid])),
#             finish_url=request.build_absolute_uri(reverse('session-finish', args=[session.uid])),
#             session_id=session.uid
#         )
#         if active_session.count():
#             # Todo: put this on error list
#             result['warnings'] = dict(
#                 incomplete_sessions_invalidated=SessionSerializer(
#                     active_session, many=True, context={'request': request}).data
#             )
#         # Todo: send update to MSP
#         return Response(result)


class EvseSerialnumberSerializer(fields.CharField):
    def to_internal_value(self, data):
        try:
            return Evse.objects.get(uid=data)
        except Evse.DoesNotExist:
            raise ValidationError(f'Evse with ID `{data}` does not exist')


class TokenIdSerializer(fields.CharField):
    def to_internal_value(self, data):
        try:
            return Token.objects.get(uid=data)
        except Token.DoesNotExist:
            raise ValidationError(f'Token with ID `{data}` does not exist')


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
        }.get(data)
        if not result:
            raise ValidationError(f"'{data}' is not a know OCPP status")
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
    session_id = serializers.CharField(
        max_length=36,
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
        default=uuid.uuid4()
    )
    start_kwh = serializers.FloatField(
        help_text='The kWh measurement at the meter at start of the transaction'
    )


class StopTransactionSerializer(serializers.Serializer):
    """
    The session ends with a specific meter value
    """
    session_id = serializers.CharField(
        max_length=36,
        help_text='The session ID on the CPO platform or order number from the billing system',
    )
    stop_kwh = serializers.FloatField(
        help_text='The kWh measurement at the time when the charging session ends',
    )


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
        ).get(self.action_map.get('post'), StatusChangeSerializer)

    @action(methods=('GET', 'POST'), detail=False)
    def status_change(self, request):
        """
        Update the charge point availability to the roaming network parties
        """
        try:
            if request.method == 'POST':
                serializer = StatusChangeSerializer(data=request.data)
                if serializer.is_valid():
                    ocpp_status = serializer.validated_data.get('status')

                    # Todo: Filter just our evses
                    evse: Evse = serializer.validated_data.get('evse')

                    evse.status = ocpp_status
                    evse.save()
                    return Response(
                        dict(
                            status_text=f'EVSE status has been changed',
                            evse=evse.uid,
                            evse_status=evse.status,
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
        Authorize charging using a specific RFID token

        Authorize request will return one of the following: HTTP_200_OK, HTTP_404_NOT_FOUND or
        HTTP_401_UNAUTHORIZED.

        Feel free to make this request multiple times,
        and you will get back the same authorization_reference
        for the next 15 minutes starting from the first authorization request.
        """
        try:
            if request.method == 'POST':
                serializer = AuthorizationSerializer(data=request.data)
                if serializer.is_valid():
                    evse: Evse = serializer.validated_data.get('evse')
                    token: Token = serializer.validated_data.get('token')
                    authorization_method, authorization_reference = authorize_token(token, evse.location)
                    if not authorization_reference or not token.valid:
                        return Response(
                            dict(status=f'Token `{token}` is (temporarily) not valid'),
                            status=status.HTTP_401_UNAUTHORIZED
                        )

                    return Response(
                        dict(
                            status_text=f'Token authorized for charging',
                            evse=evse.uid,
                            token=str(token),
                            authorization_reference=authorization_reference,
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
        Start the charging transaction (which equals the OCPI session in the roaming network).
        The session will be started regardless of charger status, in case some status change messages
        have been lost on the way.
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
                                status=status.HTTP_409_CONFLICT,
                            )
                        )
                    session = create_session(
                        # Todo: Make sure overlapping evse.uid is not a problem for CPO + eMSP role
                        # Other CPO can have same ID
                        uid=session_id, evse_id=evse, location_id=evse.location, connector_id=connector_id,
                        token_id=token, billed_to=token.party(),
                    )
                    return Response(
                        dict(
                            status_text=f'Session started',
                            session_id=session_id,
                            location=str(evse.location),
                            evse=evse.uid,
                            connector_id=connector_id,
                            billed_to=token.party(),
                            token_id=str(token),
                            start_kwh=start_kwh,
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
        Update the session progress, such as the accumulated kWh
        """
        try:
            if request.method == 'POST':
                serializer = MeterValuesSerializer(data=request.data)
                if serializer.is_valid():
                    session_id = serializer.validated_data['session_id']
                    kwh = serializer.validated_data['kwh']
                    return Response(
                        dict(
                            status_text=f'Session updated',
                            session_id=session_id,
                            kwh=kwh,
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
    def stop_transaction(self, request):
        """
        Stop the transaction, charging has been finished
        """
        try:
            if request.method == 'POST':
                serializer = StopTransactionSerializer(data=request.data)
                if serializer.is_valid():
                    session_id = serializer.validated_data['session_id']
                    stop_kwh = serializer.validated_data['kwh']
                    return Response(
                        dict(
                            status_text=f'Session finished',
                            session_id=session_id,
                            kwh=stop_kwh,
                            charge_detail_record=dict(sorry='CDR will be included here in the future'),
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

    Here you can try out the CPO API interfaces to support your development and integration work.
    These streamlined interfaces provide the necessary tools for quickly connecting
    a CPO backend to eMSPs and hubs which use the OCPI protocol.

    All the objects in the OCPI Connector are available for browsing
    and selective modification in the admin tools.
    It also provides tools for maintaining users, groups and their access to the OCPI Connector.

    To start roaming, these integrations are required from the CPO:

    1. Charge point status change (CPO => OCPI Connector)
    1. Metervalues (CPO => OCPI Connector)
    1. Remote commands (eMSP => OCPI Connector => CPO)

    If you have more than 10 charge points, you can optionally implement
    Location, evse and connector export (CPO => OCPI Connector)

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
