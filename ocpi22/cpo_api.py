import os
import uuid

from django.conf import settings
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from icecream import ic
from rest_framework import routers, status, mixins, viewsets, serializers
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.viewsets import GenericViewSet

from ocpi22.api import HyperlinkedModelSerializerCleanedUp, OCPIViewSetMixin, clear_empty
from ocpi22.models import Evse, Session, Token, Connector, Cdr


class EvseSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Evse
        fields = ['url', 'uid', 'status', 'last_updated']


class EvseViewSet(mixins.RetrieveModelMixin,
                  mixins.UpdateModelMixin,
                  mixins.DestroyModelMixin,
                  mixins.ListModelMixin,
                  OCPIViewSetMixin,
                  GenericViewSet):
    """
    This is an optimised subset of the EVSE information available in the OCPI Connector.
    """
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status']

    @action(methods=['GET', 'PATCH'], detail=False,
            url_path='(?P<evse_id>[^/.]+)', url_name='by-id-cpo')
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
                  'location_id', 'evse_uid', 'connector_id', 'meter_id', 'currency',
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


class SessionViewSet(viewsets.ViewSet):
    """
    When a driver starts charging using an RFID at the charge point, first the CPO needs to send a "start session"
    to the below URL using a GET.

    * The start url GET /api/cpo/v1/session/start/{evse_id}/{connector_id}/{token_id}/
    """
    queryset = Session.objects.all().order_by('created')

    @action(methods=['PATCH'], detail=False, url_name='update',
            url_path='update/(?P<session_id>[^/.]+)')
    def update_session(self, request, session_id) -> Response:
        """
        After the session has been started, it is recommended to send an update with each kWh consumed,
        so that the driver can monitor the progress of
        the charging session. This is done by sending a PATCH to this URL, for example { "kwh": 10 }. You can
        try it in the input bow below.

        * To update a session, send a PATCH to /api/cpo/v1/session/update/{session_id}/
        with a body containing the updated fields in JSON format

        * Finally, to finish the session, send the last update and then a GET to /api/cpo/v1/session/finish/{session_id}/
        """
        session = get_object_or_404(Session, uid=session_id)
        serializer = SessionSerializer(session, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            if serializer.validated_data['kwh']:
                serializer.validated_data['status'] = 'ACTIVE'
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
        Cdr.objects.create(
            start_date_time=session.start_date_time,
            end_date_time=session.end_date_time,
            session_id=session.uid,
            cdr_token=session.cdr_token,
            auth_method=session.auth_method,
            # Todo: format in json
            cdr_location=session.location.uid,
            currency=session.currency,
            # Todo: format in json
            tariffs=session.connector.tariff(),
            total_cost_excl_vat=session.total_cost_excl_vat,
            total_cost_inc_vat=session.total_cost_incl_vat,
            total_energy=session.kwh,
            total_time=(session.end_date_time - session.start_date_time).seconds / 3600.0
        )
        # Todo: Send CDR to MSP
        return Response(SessionSerializer(session).data)

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
                incomplete_sessions_invalidated=SessionSerializer(active_session, many=True).data
            )
        # Todo: send update to MSP
        return Response(result)


class ChargePointOperatorAPIView(routers.APIRootView):
    """
    Welcome to the OCPI Connector Developer Central. Here you can try out the CPO API interfaces to support
    the development and integration work.
    These simplified interfaces provide the necessary tools for connecting a CPO backend to eMSPs and hubs which
    use the OCPI protocol.

    Some additional information is available from OCPI Connector using the OCPI 2.2 interfaces,
    which are available at [/ocpi/2.2/](/ocpi/2.2/).

    All the objects in the OCPI Connector are available for browsing
    and selective modification at [the Admin User Interface](/admin/).
    It also provides tools for maintaining users, groups and their access to the OCPI Connector.

    To enable roaming, these integrations are required from the CPO:

    1. Location, evse and connector export (CPO => OCPI Connector)
    1. Charge point status change (CPO => OCPI Connector)
    1. Remote commands (CPO <= OCPI Connector)
    1. Session start, update and end (CPO => OCPI Connector)

    For more details, click the examples below and you will find the step-by-step technical documentation.

    """

    def get(self, request, *args, **kwargs):
        """
        Compile the example URLs for the front page
        """
        evse = Evse.objects.all()[0]
        connector = Connector.objects.filter(evse=evse)[0]
        token = Token.objects.exclude(uid='POSITIVE_TEST_TOKEN')[0]

        result = dict(
            example_session_start=request.build_absolute_uri(
                reverse('session-start', args=[evse.uid, connector.uid, 'POSITIVE_TEST_TOKEN'])
            ),
            example_session_not_authorised=request.build_absolute_uri(
                reverse('session-start', args=[evse.uid, connector.uid, token.uid])
            ),
            how_to_update_charger_status=request.build_absolute_uri(
                reverse('evse-by-id-cpo', args=[evse.uid])
            ),
        )
        return Response(result)


class CPORouter(routers.DefaultRouter):
    APIRootView = ChargePointOperatorAPIView
