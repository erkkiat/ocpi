import json
from datetime import time, date

from django.urls import reverse_lazy
from django.utils.datetime_safe import datetime

import pytz
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.decorators import method_decorator
from django.utils.safestring import mark_safe
from rest_framework.fields import DateTimeField

import ocpi22.logging as logging
from typing import Union, Optional

import redis
from django.conf import settings
from django.db import IntegrityError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import routers, status, mixins
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response

from ocpi22.viewsets import FlowchartViewSet
from util import reverse, url_link, redis_store, time_lte, time_lt
from rest_framework.viewsets import GenericViewSet

from ocpi22.choices import OcpiRolesEnum, get_language, MessageTexts, AuthorizationEnum
from ocpi22.commands.serializers import CpoCommandResultSerializer, CommandResultSerializer
from ocpi22.cpo.serializers import CpoSessionSerializer, \
    StatusChangeSerializer, AuthorizationSerializer, MeterValuesSerializer, StartTransactionSerializer, \
    StopTransactionSerializer, EvseSerializer, LocationQuickSerializer, \
    CPOStartWebhookSerializer, CPOStopWebhookSerializer, CPOReserveNowWebhookSerializer, InvoicingCallbackSerializer
from ocpi22.generic_views import WebhookViewSet
from ocpi22.messages import messages
from ocpi22.models.cdr import Cdr
from ocpi22.models.tariff import TariffElement
from ocpi22.routing import find_credentials
from ocpi22.util import command_store
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.ocpi.serializers import CdrSerializer
from ocpi22.ocpi.util import generate_session_uid, options_message
from ocpi22.sessions.util import create_session, EvseOccupied
from ocpi22.tasks import send_ocpi_request
from ocpi22.tokens.auth import authorize_token, TokenAuthorization, get_session_by_adhoc_token
from ocpi22.tokens.util import get_token_id
from ocpi22.logging import log_error

from pprint import PrettyPrinter

from ocpi22.webhooks import send_to_webhook
from ocpiconnector.ocpi_identities import Party, get_our_party, get_our_credentialsrole
from premium import requires_premium

pp = PrettyPrinter(indent=4).pprint


class CpoEvseViewSet(mixins.RetrieveModelMixin,
                     mixins.UpdateModelMixin,
                     mixins.DestroyModelMixin,
                     mixins.ListModelMixin,
                     GenericViewSet):
    """
    This is an optimised subset of the EVSE information available in the system.
    """
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status']
    pagination_class = LimitOffsetPagination

    @staticmethod
    def put(request, evse_id=None):
        if not evse_id:
            evse_id = request.data['uid']
        evse = Evse.objects.get(uid__iexact=evse_id)
        serializer = EvseSerializer(evse, data=request.data, context={'version': request.version})
        if serializer.is_valid():
            location = serializer.save()
            location.send_updates()
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

        if request.method == 'GET':
            serializer = EvseSerializer(evse, context={'version': request.version})
            return Response(serializer.data)

        elif request.method == 'PATCH':
            serializer = EvseSerializer(evse, data=request.data, partial=True, context={'version': request.version})
            if serializer.is_valid():
                evse: Evse = serializer.save()
                evse.location.send_updates()
                return Response(serializer.data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_400_BAD_REQUEST)

    queryset = Evse.objects.all().order_by('created')
    serializer_class = EvseSerializer
    lookup_field = 'evse_id'


class LocationQuickViewSet(mixins.ListModelMixin,
                           mixins.UpdateModelMixin,
                           mixins.RetrieveModelMixin,
                           GenericViewSet):
    """
    This is the endpoint for updating locations.
    **NOTE**: All IDs should remain constant, since they are referred to by many systems in the roaming network.

    """
    queryset = Location.objects.all().order_by('created')
    serializer_class = LocationQuickSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = 'uid'

    @staticmethod
    def _put(request, uid=None, partial=False):
        try:
            uid = (uid or request.data.get('id', '')).upper()
            our_role = get_our_credentialsrole(OcpiRolesEnum.CPO)
            existing_location = Location.get_if_exists(uid__iexact=uid, ocpi_master=our_role)
            serializer = LocationQuickSerializer(data=request.data, instance=existing_location, partial=partial)

            if serializer.is_valid():
                serializer.save(ocpi_master=our_role)
                http_status = status.HTTP_200_OK if existing_location else status.HTTP_201_CREATED
                return Response(serializer.data, status=http_status)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError as e:
            return Response({'status_message': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, *args, **kwargs):
        return self._put(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        return self.put(request, *args, partial=True, **kwargs)

    @action(methods=['GET', 'PATCH', 'PUT'], detail=False,
            url_path='(?P<uid>[^/.]+)')
    def by_id(self, request, uid) -> Response:
        try:
            our_role = get_our_credentialsrole(OcpiRolesEnum.CPO)

            location = get_object_or_404(Location, uid=uid, ocpi_master=our_role)
            assert request.data.get('uid') in (uid, None), f'UID differs in request and in URL'

            if request.method == 'GET':
                serializer = LocationQuickSerializer(location, context={'request': request})
                return Response(serializer.data)

            return self._put(request, uid, partial=bool(request.method == 'PATCH'))

        except IntegrityError as e:
            return Response({'status_message': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @staticmethod
    def get_object(uid=None) -> Location:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Location, uid=uid)


# Todo: limit access to certain privilege holders


def get_evse_object(evse: Union[Evse, str]) -> Evse:
    if isinstance(evse, Evse):
        return evse
    assert isinstance(evse, str), f'Unknown type for Evse identification: {evse}'
    return Evse.get_if_exists(uid=evse)


def close_active_sessions_for_evse(evse_uid: str):
    # evse = get_evse_object(evse)
    active_sessions = Session.objects.filter(evse__uid=evse_uid, status__in=(Session.ACTIVE, Session.PENDING))
    active_sessions.update(last_updated=datetime.now(pytz.utc), status=Session.COMPLETED, end_date_time=F('last_updated'))

    for session in active_sessions:
        session.send_updates()
        logging.error(f'Completed active Session {session.uid} which has been left hanging')


def applying_tariff_element(session_instance: Session, timestamp: Union[datetime, DateTimeField] = None,
                            **_kwargs) -> Optional[TariffElement]:
    def matching_weekday(wd, wd_numbers):
        return not wd_numbers or wd in wd_numbers

    def crossing_day_boundary(start_time: time, end_time: time) -> bool:
        return start_time is not None and end_time is not None and start_time > end_time

    def in_date_range(compared_timestamp: datetime, start_date: date, end_date: date) -> bool:
        if start_date and compared_timestamp < start_date:
            return False
        if end_date and compared_timestamp >= end_date:
            return False
        return True

    location_timezone = session_instance.location.get_timezone()
    timestamp = timestamp.astimezone(location_timezone) or datetime.now(tz=location_timezone)
    weekday = timestamp.weekday()
    tariffs = session_instance.connector.get_tariffs()  # Do not use Connector.tariffs_ids directly
    for tariff in tariffs:
        element: TariffElement
        for element in tariff.tariff_elements.all():
            if in_date_range(timestamp, element.start_date, element.end_date):
                weekday_numbers = element.weekday_numbers()
                if matching_weekday(weekday, weekday_numbers):
                    if crossing_day_boundary(element.start_time, element.end_time):
                        if time_lte(element.start_time, timestamp) or time_lte(timestamp, element.end_time):
                            return element
                    elif not element.start_time or time_lte(element.start_time, timestamp):
                        if not element.end_time or time_lt(timestamp, element.end_time):
                            # Matching time range
                            return element
    return None


def create_charging_periods(session: Session):
    def process(meter_value):
        timestamp = meter_value.get('timestamp')
        tariff_element = applying_tariff_element(session, timestamp)
        meter_value['tariff_element'] = tariff_element
        if tariff_element:
            meter_value['tariff'] = tariff_element.tariff
        return meter_value

    meter_values = get_meter_values(session)
    return [process(m) for m in meter_values]


def process_meter_values(request, serializer, kwh, power=None, soc=None, session=None,
                         internal_reference=None, timestamp=None):
    next_url = reverse('chargepoint-stop-transaction')
    timestamp = timestamp or datetime.now(pytz.utc)
    session = session or internal_reference

    # We found a valid Session
    if session and session.status == Session.ACTIVE:
        if not session.connector.tariff_ids.count():
            raise RuntimeError(f'EVSE {session.evse} connector {session.connector} has no tariffs')
        session.stop_kwh = kwh
        session.update_last_updated()

        # with Timer() as t:
        # store_meter_values(request, session, serializer.validated_data)
        session.update_charging_periods(kwh - session.start_kwh, soc, power, timestamp)
        # logging.info(f'Meter values stored and fetched in {float(t):.2f} seconds', request)

        session.calculate_price()
        session.save(
            update_fields=['stop_kwh', 'total_cost_incl_vat', 'total_cost_excl_vat', 'last_updated']
        )

        session_charging_periods = [cp for cp in session.chargingperiods.order_by('start_date_time')]
        session.send_updates(session_charging_periods, method='patch')

        messages.success(request,
                         mark_safe(f"You have updated the OCPI Session <b>{session.uid}</b> "
                                   f"with {kwh} kWh."))
        messages.info(request,
                      mark_safe("It's good to send the kWh and power values frequently "
                                "enough, so that the driver can see the up-to-date status "
                                "from the mobile application. For DC charging, "
                                "please update the State of Charge as well."))
        messages.success(request,
                         mark_safe(f"When you're done, next you can "
                                   f"<a href=\"{next_url}\">stop the Session</a>."))

        return Response(
            dict(
                status_text=f'Session updated',
                session_id=session.uid,
                internal_reference=session.internal_reference,
                start_kwh=session.start_kwh,
                now_kwh=kwh,
                total_kwh=session.kwh,
                power=power,
                price=session.cost(),
                soc=soc,
            )
        )
    else:
        explain = {
            Session.PENDING: 'is waiting for the CPO to start the actual charging',
            Session.INVALID: 'has never started',
            Session.COMPLETED: 'has been finished',
            Session.RESERVATION: 'is a reservation waiting for the actual charging session',
        }.get(session.status, 'is in an unknown state')
        session_admin_link = url_link(reverse('admin:ocpi22_session_changelist'),
                                      'the sessions and their statuses', target='sessions')
        messages.warning(request, mark_safe('Only active sessions can be updated, and this session has '
                                            f'the status "{session.status}", which means that it {explain}. '
                                            f'You can see {session_admin_link}.'))
        return Response(
            dict(
                status_text=f'You can only update an Session which has a status "ACTIVE".',
                session_id=session.uid,
                internal_reference=session.internal_reference,
                start_kwh=session.start_kwh,
                now_kwh=kwh,
                total_kwh=session.kwh,
                power=power,
                price=session.cost(),
                soc=soc,
            ), status=status.HTTP_403_FORBIDDEN
        )


session_key = 'session:{session.uid}'

# We should use Redis append-only lists for storing the meter values
# def store_meter_values(_request, session, data):
#     data.pop('session', None)
#     if 'timestamp' not in data:
#         data['timestamp'] = datetime.now(pytz.utc)
#     key = session_key.format(session=session)
#     assert 'timestamp' in data
#     redis_store.rpush(key, json.dumps(data, default=str))


class MeterValuesStorageSerializer(MeterValuesSerializer):
    session_id = None
    internal_reference = None

    def validate(self, attrs):
        return attrs


def get_meter_values(session):
    key = f'session:{session.uid}'
    data = redis_store.lrange(key, 0, -1)
    data = [json.loads(i) for i in data]
    serializer = MeterValuesStorageSerializer(data=data, many=True)
    assert serializer.is_valid(), serializer.errors
    return serializer.validated_data


class ChargePointViewSet(FlowchartViewSet):
    """
    The charge point is connected to roaming networks through this API. It interprets the OCPP
    status and other data from the charge point.
    """

    queryset = Location.objects.all()  # A CPO instance should only have its own Locations in the database
    lookup_field = 'uid'

    flowchart = dict(
        steps=(
            ('status_change', 'Status Change', reverse_lazy('chargepoint-status-change')),
            ('authorize', 'Authorize Token', reverse_lazy('chargepoint-authorize')),
            ('start_transaction', 'Start Transaction', reverse_lazy('chargepoint-start-transaction')),
            ('meter_values', 'Meter Values', reverse_lazy('chargepoint-meter-values')),
            ('stop_transaction', 'Stop Transaction', reverse_lazy('chargepoint-stop-transaction')),
            # Prevent Mermaid from combining these two steps, the number will be otherwise ignored (remove_numbers())
            ('status_change2', 'Status Change', reverse_lazy('chargepoint-status-change')),
        ),
        process='status_change-->authorize-->start_transaction-->meter_values-->stop_transaction-->status_change2;\n'
                'meter_values-->meter_values;\n'
    )

    def get_serializer_class(self):
        return dict(
            authorize=AuthorizationSerializer,
            status_change=StatusChangeSerializer,
            start_transaction=StartTransactionSerializer,
            meter_values=MeterValuesSerializer,
            stop_transaction=StopTransactionSerializer,
            # callbacks=CPOCallbacksSerializer,
            remote_command_result=CpoCommandResultSerializer,
        ).get(self.action_map.get('post'), StatusChangeSerializer)

    @action(methods=('GET', 'POST'), detail=False)
    def status_change(self, request):
        """
        Update the charge point availability to the roaming network parties.

        **IMPORTANT**: To prevent the EV driver from relying on malfunctioning chargers, please update the status
        whenever your monitoring notices a possible problem with the charge point. This way
        we will be able to show the real availability status to the driver.

        ## Status codes

        * `HTTP_200_OK` when the EVSE status has been successfully updated
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_404_NOT_FOUND` when the EVSE is not found

        """

        try:
            if request.method == 'POST':
                serializer = StatusChangeSerializer(data=request.data)
                if serializer.is_valid():
                    ocpp_status = serializer.initial_data.get('status')
                    ocpi_status = serializer.validated_data.get('status')
                    evse: Evse = serializer.validated_data.get('evse')

                    evse.status = ocpi_status
                    evse.last_updated = datetime.now(pytz.utc)
                    evse.location.update_last_updated()
                    evse.save()

                    if ocpi_status == Evse.AVAILABLE:
                        # Let's free up the charger for the OCPI network, in case we are out of sync
                        close_active_sessions_for_evse(evse.uid)

                    evse.send_status_updates()

                    messages.success(request,
                                     f'You have successfully changed the EVSE status to "{evse.status}". '
                                     f"Please note that the statuses in OCPP and OCPI won't always match each other "
                                     f"due to differences in protocols.")
                    next_url = reverse('chargepoint-authorize')
                    messages.success(request,
                                     mark_safe('<div>Next, you can go and '
                                               f'<a href="{next_url}">authorize a Token</a> for charging.</div>'))

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
            return Response({'status_message': options_message}, status=status.HTTP_400_BAD_REQUEST)
        except Evse.DoesNotExist as e:
            logging.error(f'Exception in CPO status_change(): {e}')
            evse_admin = reverse("admin:ocpi22_evse_changelist")
            token_admin = reverse("admin:ocpi22_token_changelist")
            messages.info(request,
                          mark_safe('Seems that the EVSE you specified does not exist. You can '
                                    f'check <a target="evseadmin" href="{evse_admin}">the list of known EVSEs</a> '
                                    'using the admin tools.'))
            return Response(
                dict(status_text=str(e)),
                status=status.HTTP_404_NOT_FOUND)

    @action(methods=('GET', 'POST'), detail=False)
    @requires_premium
    def authorize(self, request):
        """
        Authorize charging using a specific RFID token. Call this when the driver has tapped an RFID
        which is not known to your Charge Point Management System.

        **NOTE**: Authorization responses from MSPs are cached for 15 minutes, so feel free to
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
                    next_url = reverse('chargepoint-start-transaction')

                    evse: Evse = serializer.validated_data.get('evse')
                    token: Union[Token, AdhocToken, str] = serializer.validated_data.get('token')
                    authorization: TokenAuthorization = authorize_token(token, evse.location, request=request)
                    if isinstance(token, str) and authorization:
                        # This is an AD_HOC_USER or APP_USER Token
                        # eMSP has already authorized this AD HOC token for 15 minutes
                        token = AdhocToken(uid=token, valid=True, owner=authorization.party,
                                           type=authorization.token.type)

                    if not authorization:
                        token_admin = reverse('admin:ocpi22_token_changelist')
                        messages.error(request, f'The response was "{authorization.allowed}" for the Token "{token}".')
                        messages.info(request,
                                      mark_safe(
                                          f'You can <a target="tokenadmin" href="{token_admin}">browse the list of '
                                          'known Tokens in our database</a> or try one which an MSP has in their database.')
                                      )
                        return Response(
                            dict(
                                status_text='Token is (temporarily) not valid',
                                token_id=get_token_id(token),
                            ),
                            status=status.HTTP_401_UNAUTHORIZED
                        )
                    elif authorization.allowed == AuthorizationEnum.ALLOWED:
                        messages.success(request,
                                         mark_safe('Next, you can '
                                                   f'<a href="{next_url}">start the charging session</a>. '
                                                   f'Make sure to use the Token "{get_token_id(token)}", '
                                                   f'which has been authorized. The authorization expires in 15 minutes.'))

                    return Response(
                        dict(
                            allowed=authorization.allowed,
                            status_text=get_language('xx', authorization.info) or
                                        get_language('en', authorization.info) or '',
                            display_text=authorization.info or '',
                            evse_id=evse.uid,
                            token_id=token.uid,
                            token_type=token.type,
                            billed_to=token.party(),
                            authorization_reference=authorization.authorization_reference,
                            authorization_method=authorization.auth_method,
                        ), status=status.HTTP_200_OK if authorization.allowed == AuthorizationEnum.ALLOWED
                        else status.HTTP_401_UNAUTHORIZED
                    )
                else:
                    return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response({'status_message': options_message}, status=status.HTTP_400_BAD_REQUEST)

        except (Evse.DoesNotExist, Token.DoesNotExist, ValueError, OSError) as e:
            logging.error(f'Exception in CPO authorize(): {e}')
            evse_admin = reverse("admin:ocpi22_evse_changelist")
            token_admin = reverse("admin:ocpi22_token_changelist")
            messages.info(request,
                          mark_safe('Seems that the ID for the EVSE or the Token was not quite correct. You can '
                                    f'check <a target="evseadmin" href="{evse_admin}">the list of known EVSEs</a> '
                                    f'and <a target="tokenadmin" href="{token_admin}">the list of known Tokens</a> '
                                    'using the admin tools.'))
            return Response(
                dict(status_message=str(e)),
                status=status.HTTP_404_NOT_FOUND)

    @action(methods=('GET', 'POST'), detail=False)
    @requires_premium
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
        * `HTTP_401_UNAUTHORIZED` when the APP_USER token has expired
        * `HTTP_404_NOT_FOUND` when the Token or the EVSE doesn't exist
        * `HTTP_409_CONFLICT` when a Session with the same internal_reference already exists or the EVSE is occupied
        """
        try:
            next_url = reverse('chargepoint-meter-values')
            session: Session = Session.objects.none()

            if request.method == 'POST':
                serializer = StartTransactionSerializer(data=request.data,
                                                        context={'version': request.version, 'request': request})
                if serializer.is_valid():
                    evse: Evse = serializer.validated_data['evse']
                    connector_id: str = serializer.validated_data['connector_id']
                    internal_reference = serializer.validated_data.get('internal_reference')
                    token = serializer.validated_data['token']
                    start_kwh = serializer.validated_data['start_kwh']

                    if internal_reference and Session.objects.filter(internal_reference=internal_reference).exists():
                        return Response(
                            dict(
                                status_text=f'Session with internal reference `{internal_reference}` already exists',
                            ),
                            status=status.HTTP_409_CONFLICT,
                        )

                    if serializer.is_adhoc_token():
                        authorization: TokenAuthorization = authorize_token(token)
                        if not authorization:
                            return Response(dict(
                                status_text='Token is (no longer) valid',
                                token_id=get_token_id(token),
                            ), status=status.HTTP_401_UNAUTHORIZED)
                        party = authorization.party
                        session = get_session_by_adhoc_token(token, max_age_minutes=14)
                        if session:
                            session.connector = Connector.get_if_exists(uid=connector_id, evse=evse)
                            session.internal_reference = internal_reference or None
                            session.status = Session.ACTIVE
                            session.authorization_reference = authorization.authorization_reference
                            if session.connector and session.connector.tariff_ids:
                                first_tariff = session.connector.tariff_ids.first()
                                if first_tariff:
                                    session.currency = first_tariff.currency
                            session.save(update_fields=[
                                'connector', 'internal_reference', 'status', 'authorization_reference', 'currency'
                            ])
                        else:
                            credentials = find_credentials(party)
                            session = create_session(
                                evse.location.uid, evse.uid, connector_id, party,
                                credentials, internal_reference, authorization.token, session_status=Session.ACTIVE,
                                authorization_method=Session.AUTH_REQUEST,  # Already authorized above
                                authorization_reference=authorization.authorization_reference
                            )
                        logging.info(f'New session {session.uid} active at {evse.evse_id}')
                    else:
                        party = token.party()

                    if not session:
                        credentials = request.credentials if hasattr(request, 'credentials') else None
                        # Todo: Session.currency needs to match with Tariff currency
                        session = create_session(
                            uid=generate_session_uid(), internal_reference=internal_reference,
                            evse_uid=evse, location_id=evse.location, connector_id=connector_id,
                            token_id=get_token_id(token), billed_to=party, start_kwh=start_kwh, stop_kwh=start_kwh,
                            session_status=Session.ACTIVE, credentials=credentials,
                            ocpi_master=get_our_credentialsrole(OcpiRolesEnum.CPO)
                        )
                        logging.info(f'Created session {session.uid} based on start_transaction from CPO')
                    session.send_updates()
                    messages.info(
                        request,
                        {
                            Session.COMMAND:
                                'This Session is based on an authorization which was '
                                f'implied when receiving the remote command from MSP {session.billed_to}.',
                            Session.AUTH_REQUEST:
                                f'This Session was authorized by MSP {session.billed_to}.',
                            Session.WHITELIST:
                                'No authorization was requested from an MSP, because the Token '
                                'is whitelisted and hence no authorization is to be done.'
                        }.get(session.auth_method, '')
                    )
                    messages.success(request,
                                     mark_safe('A new OCPI Session has been started. '
                                               f'Store the Session ID, <b>{session.uid}</b>. '
                                               'You will need it for meter_values and stop_session.'))
                    messages.success(request,
                                     mark_safe('<div>Next, you can go and send some '
                                               f'<a href="{next_url}">meter values</a>.</div>'))

                    session_serializer = CpoSessionSerializer(instance=session,
                                                              context={'version': request.version, 'request': request})
                    return Response(
                        dict(
                            status_text=f'Session started',
                            session=session_serializer.data,
                        )
                    )
                else:
                    messages.error(request, 'Unable to start the session you requested, '
                                            'please check that the parameters are as required. '
                                            'You can find the schema by pressing "OPTIONS".')
                    return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response({'status_message': options_message}, status=status.HTTP_400_BAD_REQUEST)

        except (Evse.DoesNotExist, Token.DoesNotExist, Connector.DoesNotExist) as e:
            logging.error(f'Exception in start_transaction(): {e}', request=request)
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)
        except EvseOccupied as e:
            stop_transaction_url = reverse('chargepoint-stop-transaction')
            status_change_url = reverse('chargepoint-status-change')
            messages.error(request,
                           mark_safe(f'{e} You can complete active sessions using the '
                                     f'<a href="{stop_transaction_url}">stop_transaction</a> or by '
                                     f'<a href="{status_change_url}">changing the EVSE status</a> to "AVAILABLE".'))
            return Response(
                dict(status=str(e)),
                status=status.HTTP_409_CONFLICT)

    @action(methods=('GET', 'POST'), detail=False)
    @requires_premium
    def meter_values(self, request):
        """
        Update the session progress, so that the MSP and finally the end user will see the status
        and kWh of the current charging session. This endpoint should be called at least once per minute with the
        up to date information about the ongoing charging session, preferably every 10-15 seconds.

        ## Status codes

        * `HTTP_200_OK` when the session was updated with the provided meter values
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_403_FORBIDDEN` when the session is not active
        * `HTTP_404_NOT_FOUND` when the session doesn't exist
        * `HTTP_409_CONFLICT` when the applicable Tariff is misconfigured

        ## Energy

        The used energy is calculated by `kwh - start_kwh` (given in `start_transaction`).

        """
        try:

            if request.method == 'POST':
                serializer = MeterValuesSerializer(data=request.data,
                                                   context={'version': request.version, 'request': request})
                if serializer.is_valid():
                    return process_meter_values(request, serializer, **serializer.validated_data)
                else:
                    return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response({'status_message': options_message}, status=status.HTTP_400_BAD_REQUEST)

        except (Evse.DoesNotExist, Token.DoesNotExist, Session.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)
        except (ValidationError, RuntimeError) as e:
            # ic(e)
            logging.error(f'Exception in meter_values(): {e}', request=request)
            return Response(
                dict(status=str(e)),
                status=status.HTTP_409_CONFLICT)

    @action(methods=('GET', 'POST'), detail=False)
    @requires_premium
    def stop_transaction(self, request):
        """
        This call will end the OCPI Session. Call it when the cable is disconnected from the vehicle.

        **ENERGY**: The used energy is calculated by `stop_kwh - start_kwh`
        (`start_kwh` was given in `start_transaction`).

        **CHARGER STATUS**: Please update the status by using `status_change`.

        ## Status codes

        * `HTTP_200_OK` when the session was finished and Charge Detail Record was created successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_404_NOT_FOUND` when the Session doesn't exist
        * `HTTP_409_CONFLICT` when the Session has already been finished earlier
        """
        try:
            if request.method == 'POST':
                serializer = StopTransactionSerializer(data=request.data,
                                                       context={'version': request.version, 'request': request})
                if serializer.is_valid():
                    session = serializer.validated_data.get('session',
                                                            serializer.validated_data.get('internal_reference'))
                    stop_kwh = serializer.validated_data.get('stop_kwh')
                    stop_timestamp = serializer.validated_data.get('stop_timestamp', datetime.now(pytz.utc))

                    if session.is_final():
                        return Response(dict(status_text='Session was completed earlier, cannot stop it twice'),
                                        status=status.HTTP_409_CONFLICT)
                    if stop_kwh:
                        session.stop_kwh = stop_kwh
                        session.update_charging_periods(kwh=session.kwh, timestamp=stop_timestamp)
                    session.status = Session.COMPLETED
                    session.end_date_time = stop_timestamp.replace(tzinfo=pytz.utc)
                    session.last_updated = datetime.now(pytz.utc)
                    session.calculate_price()
                    session.save(update_fields=['stop_kwh', 'status', 'last_updated', 'end_date_time',
                                                'total_cost_incl_vat', 'total_cost_excl_vat'])
                    session.send_updates()
                    logging.info(f'Stopped session {session.uid} at {stop_timestamp} with {session.kwh} kWh and '
                                 f'cost {session.total_cost_incl_vat} {session.currency}')

                    extra_information = {
                        Session.COMMAND:
                            '<div>This session was started by using the MSP mobile application, '
                            'but the flow is mostly the same with RFID token charging.</div>',
                        Session.AUTH_REQUEST:
                            '<div>This session was started by using an RFID token, '
                            'but the flow is mostly the same when the driver starts the charging session '
                            'using an MSP mobile application.</div>',
                    }.get(session.auth_method, '')

                    messages.success(request,
                                     mark_safe(f"You have concluded the OCPI Session <b>{session.uid}</b> "
                                               f"with {session.kwh} kWh. At this point, the OCPI Charge Detail Record is "
                                               f"created automatically, and if you have set your URL for the "
                                               f"invoicing webhook, the CDR is sent to the webhook. "
                                               f"{extra_information}"))

                    # Create the corresponding CDR (it will also be sent to other party)
                    from ocpi22.models.cdr import Cdr
                    cdr = Cdr.create_based_on_session(session)

                    cdr_json = CdrSerializer(instance=cdr, context={'version': request.version, 'request': request})
                    session_serializer = CpoSessionSerializer(instance=session,
                                                              context={'version': request.version, 'request': request})

                    return Response(
                        dict(
                            status_text='Session finished',
                            session_id=session.uid,
                            internal_reference=session.internal_reference,
                            kwh_total=session.kwh,
                            session=session_serializer.data,
                            charge_detail_record=cdr_json.data
                        )
                    )
                else:
                    return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response({'status_message': options_message}, status=status.HTTP_400_BAD_REQUEST)

        except (Evse.DoesNotExist, Token.DoesNotExist, Session.DoesNotExist) as e:
            logging.error(f'Exception in stop_transaction(): {e}', request=request)
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)

    @action(methods=('GET', 'POST'), detail=False,
            url_path='remote_command_result(?:/(?P<command_id>[^/.]+))?')
    def remote_command_result(self, request, command_id=None):
        """
        Using this endpoint you indicate the success of the requested remote command.
        You'll need the command_id in the URL, so you must use the exact response_url you get when
        we call your start_transaction callback.

        ## Status codes

        * `HTTP_200_OK` when the call was succesful
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way

        """
        try:
            if request.method == 'GET':
                return Response({'status_message': options_message}, status=status.HTTP_400_BAD_REQUEST)

            command = command_store[command_id]

            if request.method == 'POST':
                serializer = CpoCommandResultSerializer(data=request.data,
                                                        context={'version': request.version, 'request': request})
                if serializer.is_valid():
                    token_element = command.get('token') or command.get('ad_hoc_token')
                    token_id = token_element.get('uid') if token_element else ''
                    session = get_session_by_adhoc_token(token_id, max_age_minutes=15)
                    if not session:
                        return Response(
                            dict(
                                status_text='Session not found',
                                token_id=token_id,
                                authorization_reference=command['authorization_reference'],
                            ), status=status.HTTP_400_BAD_REQUEST
                        )
                    result = serializer.validated_data.get('result')
                    if result == CpoCommandResultSerializer.ACCEPTED:
                        message = MessageTexts.get('PREPARING_TO_CHARGE')
                    else:
                        message = MessageTexts.get(result, MessageTexts.get('DEFAULT_CHARGER_ERROR_TEXT'))
                    params = dict(
                        result=result,
                        message=message
                    )
                    ocpi_serializer = CommandResultSerializer(instance=params)
                    response_url = command.get('response_url')
                    party = session.billed_to.split('*')
                    to = Party(*party)
                    sender = get_our_party(OcpiRolesEnum.CPO)

                    # Send CommandResponse to MSP
                    response = send_ocpi_request(
                        data=ocpi_serializer.data,
                        url=response_url,
                        token_base64=session.credentials.theirs_base64(),
                        to_country_code=to.country_code,
                        to_party_id=to.party_id,
                        from_country_code=sender.country_code,
                        from_party_id=sender.party_id,
                        method='post',
                        credentials_id=session.credentials.pk,
                        timeout=15
                    )

                    # Invalidate the session in case an error has occured
                    if result != CpoCommandResultSerializer.ACCEPTED:
                        session.status = Session.INVALID
                        session.save()
                        # Update the session to MSP, but only after the CommandResult above
                        session.send_updates()

                    return Response(
                        dict(
                            status_text=f'Response received from eMSP',
                            token_id=token_id,
                            authorization_reference=command['authorization_reference'],
                            data=response.get('json') if response else '',
                        ), status=response.get('status_code') if response else status.HTTP_503_SERVICE_UNAVAILABLE
                    )
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except redis.exceptions.ConnectionError as e:
            logging.error(f'Cannot read and store callback settings  '
                          f'due to trouble connecting with Redis: {e}', request=request)
            return Response(
                dict(
                    status_text='Unable to store settings due to connection problem. '
                                'This is our fault, sorry. Support has been alerted.'
                ),
                status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except KeyError as e:
            log_error(request, str(e))
            return Response(
                dict(
                    status_text=f'Unable to find eMSP remote command from cache, '
                                f'either the command ID (in URL) is incorrect or '
                                f'the command was issued by eMSP too long ago '
                                f'(expiration is set to {settings.REMOTE_COMMAND_EXPIRATION})'
                ),
                status=status.HTTP_404_NOT_FOUND)

        return Response(f'{request.method} is not supported', status=status.HTTP_400_BAD_REQUEST)

    def get_view_name(self):
        if self.name:
            return f'{self.name.capitalize()}'
        return f'Status Change'

    @staticmethod
    def get_object(uid=None) -> None:
        # Needed for OPTIONS to work in list view
        return None


msp_remote_commands_flowchart = dict(
    steps=(
        ('reserve_now_webhook', 'Reserve Now Webhook', reverse_lazy('cpo-reserve-now-webhook')),
        ('start_transaction_webhook', 'Start Transaction Webhook', reverse_lazy('cpo-start-transaction-webhook')),
        ('remote_command_result', 'Remote Command Result'),
        ('stop_transaction_webhook', 'Stop Transaction Webhook', reverse_lazy('cpo-stop-transaction-webhook')),
        ('invoicing_webhook', 'Invoicing Webhook', reverse_lazy('msp-invoicing-webhook')),
    ),
    process='reserve_now_webhook-->remote_command_result; start_transaction_webhook-->remote_command_result; '
            'stop_transaction_webhook-->remote_command_result; stop_transaction_webhook-->invoicing_webhook;'
)


class CpoReserveNowWebhookViewSet(WebhookViewSet):
    """
    You need to tell the system where to send remote ReserveNow commands.
    Using this endpoint you can set and get your callback URL and
    user credentials needed for accessing the endpoint.

    Example URL: `https://your.emsp.backend.server/reserve/{location_id}/{token_id}/`. The token_id will be substituted with
    the corresponding parameter from the data sent to this URL. For details, please use "OPTIONS".

    > **BASIC AUTHENTICATION**: Include user credentials and port in URL,
    > for example `https://user:password@example.com:1234/path/to/my/endpoint/`.

    ## Status codes

    * `HTTP_200_OK` when the webhook was set successfully
    * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
    """
    serializer_class = CPOReserveNowWebhookSerializer
    serializer = serializer_class()
    queryset = Location.objects.none()
    flowchart = msp_remote_commands_flowchart

    @action(methods=('GET', 'POST', 'PATCH'), detail=False, url_path='reserve_now')
    def reserve_now_webhook(self, request):
        return self.webhook(request)


class CpoStartWebhookViewSet(WebhookViewSet):
    """
    These endpoints are used for receiving remote commands from MSPs.
    Using this endpoint you can set and get your callback URL and
    user credentials needed for accessing the endpoint.

    Example URL: `https://your.emsp.backend.server/start_charging/{token_id}/`. The token_id will be substituted with
    the corresponding parameter from the data sent to this URL. For details, please use "OPTIONS".

    > **BASIC AUTHENTICATION**: Include user credentials and port in URL,
    > for example `https://user:password@example.com:1234/path/to/my/endpoint/`.

    ## Status codes

    * `HTTP_200_OK` when the webhook was set successfully
    * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
    """
    serializer_class = CPOStartWebhookSerializer
    serializer = serializer_class()
    queryset = Location.objects.none()
    flowchart = msp_remote_commands_flowchart

    @action(methods=('GET', 'POST', 'PATCH'), detail=False, url_path='start_transaction')
    def start_transaction_webhook(self, request):
        return self.webhook(request)


class CpoStopWebhookViewSet(WebhookViewSet):
    """
    These endpoints are used for receiving remote commands from MSPs.
    Using this endpoint you can set and get your callback URL and
    user credentials needed for accessing the endpoint.

    Example URL: `https://your.emsp.backend.server/stop_charging/{token_id}/`. The token_id will be substituted with
    the corresponding parameter from the data sent to this URL. For details, please use "OPTIONS".

    > **BASIC AUTHENTICATION**: Include user credentials and port in URL,
    > for example `https://user:password@example.com:1234/path/to/my/endpoint/`.

    ## Status codes

    * `HTTP_200_OK` when the webhook was set successfully
    * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
    """
    serializer_class = CPOStopWebhookSerializer
    serializer = serializer_class()
    queryset = Location.objects.none()
    flowchart = msp_remote_commands_flowchart

    @action(methods=('GET', 'POST', 'PATCH'), detail=False, url_path='stop_transaction')
    def stop_transaction_webhook(self, request):
        return self.webhook(request)


class InvoiceWebhookViewSet(WebhookViewSet):
    """
    This webhook will receive the invoicing data (Charge Detail Records).

    Using this endpoint you can set and get your callback URL and
    user credentials needed for accessing the endpoint.

    Example URL: `https://your.emsp.backend.server/session/{session_id}/`. The session_id will be substituted with
    the corresponding parameter from the data sent to this URL. For details, please use "OPTIONS".

    > **BASIC AUTHENTICATION**: Include user credentials and port in URL,
    > for example `https://user:password@example.com:1234/path/to/my/endpoint/`.

    ## Status codes

    * `HTTP_200_OK` when the webhook was set successfully
    * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
    """
    serializer_class = InvoicingCallbackSerializer
    serializer = serializer_class()
    queryset = Session.objects.none()
    flowchart = msp_remote_commands_flowchart

    @action(methods=('GET', 'POST', 'PATCH'), detail=False, url_path='invoice')
    def invoicing_webhook(self, request):
        return self.webhook(request)


class ChargePointOperatorAPIView(routers.APIRootView):
    """
    This API is not a part of the OCPI protocol. It is the ChargerHub.EU roaming API for CPOs,
    a shortcut to roaming across OCPI networks.

    > You can use these CPO API interfaces interactively
    > to support your development and integration work.
    > These streamlined interfaces provide the necessary tools for quickly but comprehensively connecting
    > a CPO backend to eMSPs and roaming hubs.

    **ADMIN UI**: All the objects in the system are available for browsing
    and selective modification in the admin tools.
    It also provides tools for maintaining users, groups and their access to the system.

    For more details, click the links below and you will find the step-by-step technical documentation.

    """

    @method_decorator(login_required)
    def get(self, request, *args, **kwargs):
        """
        Compile the example URLs for the root page
        """

        result = dict(
            status_management=dict(
                status_change=request.build_absolute_uri(
                    reverse('chargepoint-status-change')
                )
            ),
            location_management=dict(
                locations=request.build_absolute_uri(
                    reverse('quick-location-list')
                ),
                tariffs=request.build_absolute_uri(
                    reverse('quick-tariff-list')
                )
            ),
            charging_session=dict(
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
            ),
            webhooks=dict(
                remote_commands=dict(
                    reserve_now=request.build_absolute_uri(
                        reverse('cpo-reserve-now-webhook')
                    ),
                    start_transaction=request.build_absolute_uri(
                        reverse('cpo-start-transaction-webhook')
                    ),
                    stop_transaction=request.build_absolute_uri(
                        reverse('cpo-stop-transaction-webhook')
                    ),
                    remote_command_result=request.build_absolute_uri(
                        reverse('chargepoint-remote-command-result')
                    ),
                ),
                invoice=request.build_absolute_uri(
                    reverse('cpo-invoicing-webhook')
                ),
            ),
            reports=dict(
                summary=request.build_absolute_uri(
                    reverse('billing-summary')
                ),
                list=request.build_absolute_uri(
                    reverse('billing-list')
                ),
            )
        )
        return Response(result)

    def get_view_name(self):
        return 'Charge Point Operator API'


class CPORouter(routers.DefaultRouter):
    APIRootView = ChargePointOperatorAPIView
    root_view_name = 'cpo-api'


@receiver(post_save, sender=Cdr)
def cdr_post_save(sender, instance: Cdr, created, *_args, raw, **_kwargs):
    if raw:
        return
    try:
        if not settings.TEST:
            cdr_serializer = CdrSerializer(instance)
            send_to_webhook(serialized_data=cdr_serializer.data, serializer=InvoicingCallbackSerializer)
    except Exception as e:
        logging.error(f'Unable to send the new CDR to CpoInvoiceWebhook: {e}')
