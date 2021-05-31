import os
import uuid

from django.conf import settings
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import routers, status, mixins
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.viewsets import GenericViewSet

from ocpi22.api import HyperlinkedModelSerializerCleanedUp, OCPIViewSetMixin, clear_empty
from ocpi22.models import Evse, Session, Token, Connector


class EvseSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Evse
        fields = ['url', 'uid', 'status']


class EvseViewSet(mixins.RetrieveModelMixin,
                  mixins.UpdateModelMixin,
                  mixins.DestroyModelMixin,
                  mixins.ListModelMixin,
                  OCPIViewSetMixin,
                  GenericViewSet):

    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status']

    @action(methods=['GET', 'PATCH'], detail=False,
            url_path='(?P<evse_id>[^/.]+)', url_name='by-id-cpo')
    def evse_by_id(self, request, evse_id) -> Response:
        """
        This URL is used for sending charger status updates using the PATCH method. Status updates should be
        real time, so that the eMSPs can show the current availability to their customers.

        You can try the status update by typing a different status
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
    queryset = Session.objects.all().order_by('created')

    @action(methods=['PATCH'], detail=False, url_name='update',
            url_path='update/(?P<session_id>[^/.]+)')
    def update_session(self, request, session_id) -> Response:
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
    def finish(self, request, session_id) -> Response:
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
        session.save()
        # Todo: Create and send CDR to MSP
        return Response(SessionSerializer(session).data)

    @action(methods=['GET'], detail=False,
            url_path='start/(?P<evse_id>[^/.]+)/(?P<connector_id>[^/.]+)/(?P<token_id>[^/.]+)')
    def start(self, request, evse_id, connector_id, token_id) -> Response:
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
    CPO API
    ---------------

    This portal provides ways to view the information in the database, read the API documentation and
    try out sending information to the API. The OCPI API serves both the eMSP and the CPO.

    1. The CPO specific interfaces are available at [/api/v1/cpo/](/api/v1/cpo/)
    """


class CPORouter(routers.DefaultRouter):
    APIRootView = ChargePointOperatorAPIView
