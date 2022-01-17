import logging
import os
import uuid

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
from ocpi22.location import send_evse_updates
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.models.cdr import Cdr
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
    OCPI Connector will fetch your locations nightly using this format.
    Contact support@chargerhub.eu with the URL where you provide this data.
    So, during testing you can send your development version
    data using the below input field and PUT/PATCH, and in production the OCPI Connector will fetch
    the data automatically using GET.

    Please note that all IDs should remain constant, since they are referred to by many systems.

    """

    # noinspection PyUnresolvedReferences
    def put(self, request, uid=None):
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
    # noinspection PyUnresolvedReferences
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
        pp(f'*** OCPI Connector got an update from CPO/charger for session {session_id}: {request.data}')
        session = get_object_or_404(Session, uid=session_id)
        if session.status in self.FINAL_STATUSES:
            return Response(dict(error='This session cannot be updated, since it already has a final status'),
                            status.HTTP_401_UNAUTHORIZED)
        serializer = SessionSerializer(session, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            if serializer.validated_data['kwh']:
                serializer.validated_data['status'] = 'ACTIVE'

            # Let's not try to calculate all costs before the end of the Session
            # end_date_time = session.end_date_time or timezone.now()
            # serializer.validated_data['total_cost_incl_vat'], \
            #     serializer.validated_data['total_cost_excl_vat'] = \
            #     self.calculate_price(session.connector, session.kwh,
            #                          (end_date_time - session.start_date_time).seconds / 60 / 60)

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
                error=f'Session {session_id} was already finished. {session}'
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
                uid=uuid.uuid4().hex,
                start_date_time=session.start_date_time,
                end_date_time=session.end_date_time,
                session_id=session.uid,
                cdr_token_uid=session.cdr_token_uid,
                cdr_token_type=session.cdr_token_type,
                cdr_token_contract_id=session.cdr_token_contract_id,
                auth_method=session.auth_method,
                authorization_reference=session.authorization_reference,
                cdr_location_id=session.location.uid,
                cdr_location_address=session.location.address,
                cdr_location_city=session.location.city,
                cdr_location_postal_code=session.location.postal_code,
                cdr_location_country=session.location.country,
                cdr_location_latitude=f'{session.location.latitude:.6f}',
                cdr_location_longitude=f'{session.location.longitude:.6f}',
                cdr_location_evse_uid=session.evse.uid,
                cdr_location_evse_id=session.evse.evse_id,
                cdr_location_connector_id=session.connector.uid,
                cdr_location_connector_standard=session.connector.standard,
                cdr_location_connector_format=session.connector.format,
                cdr_location_connector_power_type=session.connector.power_type,
                currency=session.currency,
                total_cost_excl_vat=session.total_cost_excl_vat,
                total_cost_incl_vat=session.total_cost_incl_vat,
                total_energy=session.kwh,
                total_time=round((session.end_date_time - session.start_date_time).seconds / 3600.0, 5)
            )
            cdr.tariffs.set(session.connector.tariff_ids.all())
            from ocpi22.api import CdrSerializer
            result['cdr'] = CdrSerializer(cdr, context={'request': request}).data

            # from ocpi22.commands import sh
            # logging.basicConfig(handlers=[sh], level=logging.INFO)
            logging.info(f'Successful charging session finished at {session.location}, EVSE: {session.evse.evse_id}, '
                         f'kwh: {session.kwh}, total time: {cdr.total_time*60:.0f} minutes, '
                         f'cost: {session.total_cost_incl_vat} {session.currency}', extra={'notify_slack': True})

        # Todo: Send CDR to MSP
        return Response(result)

    @action(methods=['GET'], detail=False, url_name='start',
            url_path='start/(?P<evse_id>[^/.]+)/(?P<connector_id>[^/.]+)/(?P<token_uid>[^/.]+)')
    def start_session(self, request, evse_id, connector_id, token_uid) -> Response:
        evse = get_object_or_404(Evse, uid=evse_id)
        location = evse.location
        connector = get_object_or_404(Connector, uid=connector_id, evse=evse)
        auth_method, authorization_info = authorize_token(token_uid, location)
        if not auth_method:
            return Response(dict(error=f'Token {token_uid} was not authorized for use by MSP at this time'),
                            status=status.HTTP_401_UNAUTHORIZED)
        if not authorization_info:
            text = f'There is technical error authorizing {token_uid}, response from MSP is missing token information.'
            logging.error(text)
            return Response(dict(error=text))
        token = authorization_info.get('token')
        # noinspection PyUnresolvedReferences
        active_session = Session.objects.filter(evse=evse, status__in=('ACTIVE', 'PENDING'))
        if active_session.count():
            logging.warning('Starting a new session while one or more previous sessions have not been finished. '
                            f'Invalidating incomplete sessions: {",".join([str(s) for s in active_session])}')
            active_session.update(status='INVALID')

        # noinspection PyUnresolvedReferences
        session = Session.objects.create(
            country_code='FI',
            party_id=os.environ.get('CPO_PARTY_ID', 'EKI'),
            uid=uuid.uuid4().hex,
            kwh=0.0,
            start_date_time=timezone.now(),
            cdr_token_uid=token.get('uid'),
            cdr_token_type=token.get('type'),
            cdr_token_contract_id=token.get('contract_id'),
            auth_method=auth_method,
            authorization_reference=authorization_info.get('authorization_reference'),
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
    Here you can try out the CPO API interfaces to support your development and integration work.
    These streamlined interfaces provide the necessary tools for quickly connecting
    a CPO backend to eMSPs and hubs which use the OCPI protocol.

    Some additional data is available from the OCPI Connector using the OCPI 2.2 interfaces
    at [/ocpi/cpo/2.2/](/ocpi/cpo/2.2/).

    All the objects in the OCPI Connector are available for browsing
    and selective modification at [the Admin User Interface](/admin/).
    It also provides tools for maintaining users, groups and their access to the OCPI Connector.

    To start roaming, these integrations are required from the CPO:

    1. Location, evse and connector export (CPO => OCPI Connector)
    1. Charge point status change (CPO => OCPI Connector)
    1. Remote commands (eMSP => OCPI Connector => CPO)
    1. Session start, update and end (CPO => OCPI Connector)

    For more details, click the examples below and you will find the step-by-step technical documentation.

    """

    # noinspection PyUnresolvedReferences
    def get(self, request, *args, **kwargs):
        """
        Compile the example URLs for the front page
        """
        try:
            evse = Evse.objects.none()
            connector = Connector.objects.none()
            evses = Evse.objects.all()
            if evses.count():
                evse = evses[0]
                connectors = Connector.objects.filter(evse=evse)
                connector = connectors[0] if connectors else Connector.objects.none()
            tokens = Token.objects.exclude(uid='POSITIVE_TEST_TOKEN')
            token = tokens[0] if tokens.count() else Token.objects.none()
            sessions = Session.objects.filter(status='ACTIVE')
            session = sessions[0] if sessions.count() else ''

            result = dict(
                session_tutorial=request.build_absolute_uri(
                    reverse('session-start', args=[evse.uid, connector.uid, 'POSITIVE_TEST_TOKEN'])
                ) if evse and connector else 'Please create an EVSE with a connector first',
                example_session_not_authorised=request.build_absolute_uri(
                    reverse('session-start', args=[evse.uid, connector.uid, token.uid])
                ) if token else 'Please create a token first',
                example_session_update=request.build_absolute_uri(
                    reverse('session-update', args=[session.uid])
                ) if session else 'Please start a new session first',
                how_to_export_locations=request.build_absolute_uri(
                    reverse('quick-location-list')
                ),
                how_to_update_charger_status=request.build_absolute_uri(
                    reverse('cpo-evse-by-id', args=[evse.uid])
                ),
            )
            return Response(result)
        except (IndexError, AttributeError):
            return Response(dict(
                tutorial='After creating some Evses with Connectors, '
                         'and some Tokens, you will see some example links here.')
            )

    def get_view_name(self):
        return 'Charge Point Operator API'


class CPORouter(routers.DefaultRouter):
    APIRootView = ChargePointOperatorAPIView
    root_view_name = 'cpo-api'
