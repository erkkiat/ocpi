import os
import uuid

from django.conf import settings
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from icecream import ic
from rest_framework import routers, status, mixins, viewsets, serializers
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.viewsets import GenericViewSet

from ocpi22 import models
from ocpi22.api import HyperlinkedModelSerializerCleanedUp, clear_empty, CdrSerializer
from ocpi22.models import Evse, Session, Token, Connector, Cdr, Location


class EvseSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Evse
        fields = ['url', 'uid', 'status', 'last_updated']

    uid = serializers.CharField(read_only=True)


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

        Some available options for status are:

        * AVAILABLE
        * CHARGING
        * REMOVED (this is used instead of deleting the EVSE, since there might be references to it)
        * PLANNED
        * More options are listed at [/api/cpo/v1/options/](/api/cpo/v1/options/)

        """
        evse = get_object_or_404(Evse, uid=evse_id)

        if request.method == 'GET':
            serializer = EvseSerializer(evse, context={'request': request})
            return Response(serializer.data)

        elif request.method == 'PATCH':
            serializer = EvseSerializer(evse, data=request.data, partial=True, context={'request': request})
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_400_BAD_REQUEST)

    # noinspection PyUnresolvedReferences
    queryset = Evse.objects.all().order_by('created')
    serializer_class = EvseSerializer


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

    @staticmethod
    def get_token(session):
        token = session.cdr_token
        return clear_empty(dict(
            uid=token.uid,
            type=token.type,
            contract_id=token.contract_id
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


def authorize_token(token):
    # Todo: send auth request to the right MSP
    if 'POSITIVE_TEST_TOKEN' in token.uid and settings.DEBUG:
        return 'WHITELIST'
    return False


class ConnectorQuickSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Connector
        fields = ['uid', 'standard', 'format',
                  'max_voltage', 'max_amperage', 'max_electric_power',
                  'tariff_ids', 'last_updated']

    uid = serializers.CharField(validators=[models.uid_validator])
    max_electric_power = serializers.SerializerMethodField()
    tariff_ids = serializers.SerializerMethodField()

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

    uid = serializers.CharField(validators=[models.uid_validator])
    connectors = ConnectorQuickSerializer(many=True)

    # def get_object(self, view_name, view_args, view_kwargs):
    #
    # def create(self, validated_data):
    #     ic(self.location)
    #     connectors = validated_data.pop('connectors')
    #     validated_data['location'] = self.location
    #     ic(validated_data)
    #     # noinspection PyUnresolvedReferences
    #     evse = Evse.objects.create(**validated_data)
    #     for connector in connectors:
    #         # noinspection PyUnresolvedReferences
    #         Connector.objects.create(evse=evse, **connector)
    #     return evse


class LocationQuickSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Location
        fields = [
            'quick_url', 'id',
            'name', 'address', 'city', 'postal_code', 'state', 'country',
            'latitude', 'longitude', 'evses',
        ]

    id = serializers.CharField(source='uid', validators=[models.uid_validator])
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
        evses = validated_data.pop('evses') if 'evses' in validated_data else []
        Location.objects.filter(uid=location.uid).update(**validated_data)
        for evse_dict in evses:
            connectors = evse_dict.pop('connectors') if 'connectors' in evse_dict else []
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
    OCPI Connector will fetch your locations nightly using this format.
    Contact support@chargerhub.eu with the URL where you provide this data.
    So, during testing you can send your development version
    data using the below input field and PUT/PATCH, and in production the OCPI Connector will fetch
    the data automatically using GET.

    Please note that all IDs should remain constant, since they are referred to by many systems.

    """

    # noinspection PyUnresolvedReferences
    def put(self, request, uid=None):
        location = None
        serializer = None

        if uid:
            # Write over an existing Location
            location: Location = get_object_or_404(Location, uid=uid)
            serializer = self.get_serializer(location, data=request.data)
        else:
            # Create a new object
            # This relies on serializer.create()
            serializer = self.get_serializer(data=request.data)

        if serializer.is_valid():
            serializer.save()
            location: Location = get_object_or_404(Location, uid=uid)
            serializer = self.get_serializer(location)
            ic(serializer.data)
            return Response(serializer.data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=['GET', 'PATCH'], detail=False,
            url_path='(?P<uid>[^/.]+)')
    def by_id(self, request, uid) -> Response:
        # noinspection PyUnresolvedReferences
        location = get_object_or_404(Location, uid=uid)

        if request.method == 'GET':
            serializer = LocationQuickSerializer(location, context={'request': request})
            return Response(serializer.data)

        elif request.method == 'PATCH':
            serializer = LocationQuickSerializer(location, data=request.data, partial=True,
                                                 context={'request': request})
            if serializer.is_valid():
                serializer.save()
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

    # Todo: fix OPTIONS button for list view


class SessionViewSet(viewsets.ViewSet):
    """
    Congratulations, you have started a session!

    This step should happen when the driver starts charging using an RFID at the charge point.
    The first step is that the CPO sends a "start session" GET to the below URL.

    * The start session URL: GET /api/cpo/v1/session/start/{evse_id}/{connector_id}/{token_id}/

    If the response contains a "incomplete_sessions_invalidated" node, that means that there was a session in progress
    at this specific EVSE. That session was invalidated, although your response shows the EVSE's earlier status.

    """
    queryset = Session.objects.all().order_by('created')
    pagination_class = LimitOffsetPagination

    FINAL_STATUSES = ('INVALID', 'COMPLETE')

    @action(methods=['PATCH'], detail=False, url_name='update',
            url_path='update/(?P<session_id>[^/.]+)')
    def update_session(self, request, session_id) -> Response:
        """
        After the session has been started, it is recommended to send an update with each kWh consumed,
        so that the driver can monitor the progress of
        the charging session. This is done by sending a PATCH to this URL, for example { "kwh": 10 }. You can
        try it in the input box below.

        * To update a session, send a PATCH to /api/cpo/v1/session/update/{session_id}/
        with a body containing the updated fields in JSON format

        * Finally, to finish the session, send the last update and then a GET to /api/cpo/v1/session/finish/{session_id}/
        """
        session = get_object_or_404(Session, uid=session_id)
        if session.status in self.FINAL_STATUSES:
            return Response(dict(error='This session cannot be updated, since it already has a final status'),
                            status.HTTP_401_UNAUTHORIZED)
        serializer = SessionSerializer(session, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            if serializer.validated_data['kwh']:
                serializer.validated_data['status'] = 'ACTIVE'
            # Todo: Create a
            serializer.save()
            # Todo: send update to MSP
            result = dict(finish_url=request.build_absolute_uri(reverse('session-finish', args=[session.uid])))
            result.update(serializer.data)
            return Response(result)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=['GET'], detail=False, url_name='finish',
            url_path='finish/(?P<session_id>[^/.]+)')
    def finish_session(self, request, session_id) -> Response:
        """
        The finish session endpoint closes the specified session regardless of its status.
        The status of a finished session is "COMPLETED", or in case kwh is 0.0, the session status will be "INVALID".

        In case this EVSE has one or more unfinished sessions left hanging,
        the response will have a list called "incomplete_sessions_invalidated",
        which shows the sessions which were discarded by changing their status to "INVALID". These sessions will not
        be billed, but they can still be found in the [admin user interface](/admin/).
        """
        session = get_object_or_404(Session, uid=session_id)
        if session.status in self.FINAL_STATUSES:
            return Response(dict(error='This session cannot be finished, since it already has a final status'),
                            status.HTTP_401_UNAUTHORIZED)

        if session.status == 'PENDING' and not session.kwh:
            session.status = 'INVALID'
        elif session.status != 'ACTIVE' and session.kwh:
            return Response(dict(
                error=f'Session {session_id} is not active or pending, so it cannot be finished.'
            ))
        else:
            session.status = 'COMPLETED'
        session.end_date_time = timezone.now()
        session.calculate_price()
        session.save()
        result = dict(session=SessionSerializer(session, context={'request': request}).data)
        if session.kwh:
            # noinspection PyUnresolvedReferences
            cdr = Cdr.objects.create(
                uid=uuid.uuid4(),
                start_date_time=session.start_date_time,
                end_date_time=session.end_date_time,
                session_id=session.uid,
                cdr_token=session.cdr_token,
                auth_method=session.auth_method,
                authorization_reference=session.authorization_reference,
                # Todo: format in json
                cdr_location=session.location.uid,
                currency=session.currency,
                total_cost_excl_vat=session.total_cost_excl_vat,
                total_cost_incl_vat=session.total_cost_incl_vat,
                total_energy=session.kwh,
                total_time=(session.end_date_time - session.start_date_time).seconds / 3600.0
            )
            cdr.tariffs.set(session.connector.tariff_ids.all())
            result['cdr'] = CdrSerializer(cdr, context={'request': request}).data
        # Todo: Send CDR to MSP
        return Response(result)

    @action(methods=['GET'], detail=False, url_name='start',
            url_path='start/(?P<evse_id>[^/.]+)/(?P<connector_id>[^/.]+)/(?P<token_id>[^/.]+)')
    def start_session(self, request, evse_id, connector_id, token_id) -> Response:
        token = get_object_or_404(Token, uid=token_id)
        evse = get_object_or_404(Evse, uid=evse_id)
        location = evse.location
        connector = get_object_or_404(Connector, uid=connector_id, evse=evse)
        auth_method = authorize_token(token)
        if not auth_method:
            return Response(dict(error=f'Token {token} was not authorized for use by MSP at this time'),
                            status=status.HTTP_401_UNAUTHORIZED)
        active_session = Session.objects.filter(evse=evse, status__in=('ACTIVE', 'PENDING'))
        if active_session.count():
            ic('Invalidating incomplete sessions', ",".join([str(s) for s in active_session]))
            active_session.update(status='INVALID')

        session = Session.objects.create(
            country_code='FI',
            party_id=os.environ.get('CPO_PARTY_ID', 'EKI'),
            uid=uuid.uuid4(),
            kwh=0.0,
            start_date_time=timezone.now(),
            cdr_token=token,
            auth_method=auth_method,
            location=location,
            evse=evse,
            connector=connector,
            currency=os.environ.get('CPO_CURRENCY', 'EUR')
        )

        result = dict(
            update_url=request.build_absolute_uri(reverse('session-update', args=[session.uid])),
            finish_url=request.build_absolute_uri(reverse('session-finish', args=[session.uid])),
            session_id=session.uid
        )
        if active_session.count():
            # Todo: put this on error list
            result['warnings'] = dict(
                incomplete_sessions_invalidated=SessionSerializer(
                    active_session, many=True, context={'request': request}).data
            )
        # Todo: send update to MSP
        return Response(result)


class ChargePointOperatorAPIView(routers.APIRootView):
    """
    Welcome to the OCPI Connector Developer Central. Here you can try out the CPO API interfaces to support
    the development and integration work.
    These streamlined interfaces provide the necessary tools for quickly connecting
    a CPO backend to eMSPs and hubs which use the OCPI protocol.

    Some additional data is available from the OCPI Connector using the OCPI 2.2 interfaces
    at [/ocpi/2.2/](/ocpi/2.2/).

    All the objects in the OCPI Connector are available for browsing
    and selective modification at [the Admin User Interface](/admin/).
    It also provides tools for maintaining users, groups and their access to the OCPI Connector.

    To start roaming, these integrations are required from the CPO:

    1. Location, evse and connector export (CPO => OCPI Connector)
    1. Charge point status change (CPO => OCPI Connector)
    1. Remote commands (CPO <= OCPI Connector)
    1. Session start, update and end (CPO => OCPI Connector)

    For more details, click the examples below and you will find the step-by-step technical documentation.

    """

    # noinspection PyUnresolvedReferences
    def get(self, request, *args, **kwargs):
        """
        Compile the example URLs for the front page
        """
        evse = Evse.objects.all()[0]
        connector = Connector.objects.filter(evse=evse)[0]
        token = Token.objects.exclude(uid='POSITIVE_TEST_TOKEN')[0]

        result = dict(
            session_tutorial=request.build_absolute_uri(
                reverse('session-start', args=[evse.uid, connector.uid, 'POSITIVE_TEST_TOKEN'])
            ),
            example_session_not_authorised=request.build_absolute_uri(
                reverse('session-start', args=[evse.uid, connector.uid, token.uid])
            ),
            how_to_export_locations=request.build_absolute_uri(
                reverse('quick-location-list')
            ),
            how_to_update_charger_status=request.build_absolute_uri(
                reverse('cpo-evse-by-id', args=[evse.uid])
            ),
        )
        return Response(result)


class CPORouter(routers.DefaultRouter):
    APIRootView = ChargePointOperatorAPIView
