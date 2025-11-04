import json
from datetime import time, date
from functools import reduce
from logging import getLogger

from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse_lazy
from django.utils.datetime_safe import datetime

import pytz
from django.contrib.auth.decorators import login_required
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.decorators import method_decorator
from django.utils.safestring import mark_safe
from ninja.errors import HttpError
from rest_framework.fields import DateTimeField
from rest_framework.permissions import IsAdminUser
from ocpi22 import ocpi_logging

from typing import Union, Optional

import redis
from django.conf import settings
from rest_framework import routers, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError

from custom_ninja_api import CustomNinjaAPI
from integrations.hubject.schemas import ChargingNotificationType
from ocpi22.cpo.schemas import LocationIn, Error
from ocpi22.cpo.session_service import SessionService
from ocpi22.cpo.session_cache import save_to_session_cache
from ocpi22.locations.services import LocationService, EvseServices
from ocpi22.models import enum
from ocpi22.ocpi.auth import NinjaBasicAuth, get_credentialsrole
from ocpi22.routing import find_route_from_credentials
from ocpi22.viewsets import FlowchartViewSet
from ocpiconnector.exception_handler import ocpi_exception_handler
from util import (
    reverse,
    url_link,
    redis_store,
    time_lte,
    time_lt,
    ErrorLoggingResponse as Response,
    RedisStore,
    markdown_escape,
)

from ocpi22.choices import (
    OcpiRolesEnum,
    MessageTexts,
    AuthorizationEnum,
    OcpiModuleEnum,
)
from ocpi22.commands.serializers import (
    CpoCommandResultSerializer,
    CommandResultSerializer,
)
from ocpi22.cpo.serializers import (
    CpoSessionSerializer,
    StatusChangeSerializer,
    AuthorizationSerializer,
    MeterValuesSerializer,
    StartTransactionSerializer,
    StopTransactionSerializer,
    CPOStartWebhookSerializer,
    CPOStopWebhookSerializer,
    CPOReserveNowWebhookSerializer,
    CPOAuthorizationResponseSerializer,
)
from ocpi22.generic_views import WebhookViewSet
from ocpi22.messages import messages
from ocpi22.models.cdr import Cdr
from ocpi22.models.tariff import TariffElement
from ocpi22.util import command_store, clear_empty
from ocpi22.models.location import Location, Evse
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.ocpi.serializers import CdrSerializer, InvoicingCallbackSerializer
from ocpi22.ocpi.util import options_message
from ocpi22.sessions.util import create_session, EvseOccupied
from ocpi22.tasks import send_ocpi_request
from ocpi22.tokens.auth import (
    authorize_token,
    TokenAuthorization,
    get_session_by_token_uid,
    get_session_by_token_uid_and_evse_uid,
    get_token_authorization_from_session,
    _authorize_token,
)
from ocpi22.tokens.util import get_token_id
from ocpi22.util import MyMetadata

from pprint import PrettyPrinter

from ocpi22.legacy_webhooks import send_to_webhook_legacy
from ocpiconnector.ocpi_identities import get_our_party, get_our_credentialsrole
from ocpiconnector.party import party_from_str, Party

pp = PrettyPrinter(indent=4).pprint
session_cache = RedisStore(namespace=settings.REDIS_SESSION_CACHE_NAMESPACE)

logger = getLogger(__name__)


def applying_tariff_element(
    session_instance: Session,
    timestamp: Union[datetime, DateTimeField] = None,
    **_kwargs,
) -> Optional[TariffElement]:
    def matching_weekday(wd, wd_numbers):
        return not wd_numbers or wd in wd_numbers

    def crossing_day_boundary(start_time: time, end_time: time) -> bool:
        return start_time is not None and end_time is not None and start_time > end_time

    def in_date_range(
        compared_timestamp: datetime, start_date: date, end_date: date
    ) -> bool:
        if start_date and compared_timestamp < start_date:
            return False
        if end_date and compared_timestamp >= end_date:
            return False
        return True

    location_timezone = session_instance.location.get_timezone()
    timestamp = (timestamp and timestamp.astimezone(location_timezone)) or datetime.now(
        tz=location_timezone
    )
    weekday = timestamp.weekday()
    tariffs = (
        session_instance.connector.get_tariffs()
    )  # Do not use Connector.tariffs_ids directly
    for tariff in tariffs:
        element: TariffElement
        for element in tariff.tariff_elements.all():
            if in_date_range(timestamp, element.start_date, element.end_date):
                weekday_numbers = element.weekday_numbers()
                if matching_weekday(weekday, weekday_numbers):
                    if crossing_day_boundary(element.start_time, element.end_time):
                        if time_lte(element.start_time, timestamp) or time_lte(
                            timestamp, element.end_time
                        ):
                            return element
                    elif not element.start_time or time_lte(
                        element.start_time, timestamp
                    ):
                        if not element.end_time or time_lt(timestamp, element.end_time):
                            # Matching time range
                            return element
    return None


def create_charging_periods(session: Session):
    def process(meter_value):
        timestamp = meter_value.get("timestamp")
        tariff_element = applying_tariff_element(session, timestamp)
        meter_value["tariff_element"] = tariff_element
        if tariff_element:
            meter_value["tariff"] = tariff_element.tariff
        return meter_value

    meter_values = get_meter_values(session)
    return [process(m) for m in meter_values]


def process_meter_values(
    request,
    kwh,
    power=None,
    soc=None,
    session=None,
    timestamp=None,
):
    next_url = reverse("chargepoint-stop-transaction")
    timestamp = timestamp or datetime.now(pytz.utc)

    if not session:
        raise ValidationError("Session needs to be provided for process_meter_values()")

    if session.status == Session.ACTIVE:
        try:
            Session.objects.prefetch_related("chargingperiods").get(pk=session.pk)
        except Session.DoesNotExist:
            logger.error(f"Session {session}  not found")

        if not session.connector.tariff_ids.count():
            raise RuntimeError(
                f"EVSE {session.evse} connector {session.connector} has no tariffs"
            )
        SessionService().update_meter_values(
            session, timestamp=timestamp, kwh=kwh, soc=soc, power=power
        )
        session.send_updates(
            method="put", update_type=ChargingNotificationType.Progress
        )
        messages.success(
            request,
            f"You have updated the OCPI Session **{markdown_escape(session.uid)}** "
            f"with {kwh} kWh.",
        )
        messages.info(
            request,
            "It's good to send the kWh and power values frequently "
            "enough, so that the driver can see the up-to-date status "
            "from the mobile application. For DC charging, "
            "please update the State of Charge as well.",
        )
        messages.success(
            request,
            f"When you're done, next you can "
            f'<a href="{next_url}">stop the Session</a>.',
        )

        return Response(
            dict(
                status_text="Session updated",
                session_id=session.uid,
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
            Session.PENDING: "is waiting for the CPO to start the actual charging",
            Session.INVALID: "has never started",
            Session.COMPLETED: "has been finished",
            Session.RESERVATION: "is a reservation waiting for the actual charging session",
        }.get(session.status, "is in an unknown state")
        session_admin_link = url_link(
            reverse("admin:ocpi22_session_changelist"),
            "the sessions and their statuses",
            target="sessions",
        )
        messages.warning(
            request,
            "Only active sessions can be updated, and this session has "
            f'the status "{session.status}", which means that it {explain}. '
            f"You can see {session_admin_link}.",
        )
        return Response(
            dict(
                status_text='You can only update a Session which has a status "ACTIVE".',
                session_id=session.uid,
                start_kwh=session.start_kwh,
                now_kwh=kwh,
                total_kwh=session.kwh,
                power=power,
                price=session.cost(),
                soc=soc,
            ),
            status=status.HTTP_403_FORBIDDEN,
        )


class MeterValuesStorageSerializer(MeterValuesSerializer):
    session_id = None

    def validate(self, attrs):
        return attrs


def get_meter_values(session):
    key = f"session:{session.uid}"
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

    queryset = (
        Location.objects.all()
    )  # Todo: A CPO instance can have locations from other partners as well
    lookup_field = "uid"
    permission_classes = [IsAdminUser]
    metadata = MyMetadata()

    flowchart = dict(
        steps=(
            (
                "status_change",
                "Status Change",
                reverse_lazy("chargepoint-status-change"),
            ),
            ("authorize", "Authorize Token", reverse_lazy("chargepoint-authorize")),
            (
                "start_transaction",
                "Start Transaction",
                reverse_lazy("chargepoint-start-transaction"),
            ),
            ("meter_values", "Meter Values", reverse_lazy("chargepoint-meter-values")),
            (
                "stop_transaction",
                "Stop Transaction",
                reverse_lazy("chargepoint-stop-transaction"),
            ),
            # Prevent Mermaid from combining these two steps, the number will be otherwise ignored (remove_numbers())
            (
                "status_change2",
                "Status Change",
                reverse_lazy("chargepoint-status-change"),
            ),
        ),
        process="status_change-->authorize-->start_transaction-->meter_values-->stop_transaction-->status_change2;\n"
        "meter_values-->meter_values;\n",
    )

    return_values = dict(
        authorize=dict(post=CPOAuthorizationResponseSerializer),
        start_transaction=dict(post=CpoSessionSerializer),
        meter_values=dict(post=CpoSessionSerializer),
        stop_transaction=dict(post=CpoSessionSerializer),
    )

    def get_extra_metadata(self, _request) -> dict:
        return clear_empty(
            dict(
                return_value={
                    http_method.upper(): self.metadata.get_serializer_info(
                        self.metadata.ensure_serializer_instance(
                            self.return_values.get(method_name, {}).get(http_method)
                        )
                    )
                    for http_method, method_name in getattr(
                        self, "action_map", {}
                    ).items()
                }
            )
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
        ).get(self.action_map.get("post"), StatusChangeSerializer)

    @action(methods=("GET", "POST"), detail=False)
    def status_change(self, request):
        """
        Update the charge point availability to the roaming network parties.

        {{flowchart}}

        **IMPORTANT**: To prevent the EV driver from relying on malfunctioning chargers, please update the status
        whenever your monitoring notices a possible problem with the charge point. This way
        we will be able to show the real availability status to the driver.

        ## Status Codes

        * `HTTP_200_OK` when the EVSE status has been successfully updated
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_404_NOT_FOUND` when the EVSE is not found

        """

        try:
            if request.method == "POST":
                serializer = StatusChangeSerializer(data=request.data)
                if serializer.is_valid():
                    # Todo: Store the status change in the database for converting to ChargingPeriods

                    ocpp_status = serializer.initial_data.get("status")
                    ocpi_status = serializer.validated_data.get("status")
                    evse: Evse = serializer.validated_data.get("evse")

                    evse.status = ocpi_status
                    evse.last_updated = datetime.now(pytz.utc)
                    # Todo: update Location
                    evse.save(update_fields=["status", "last_updated"])

                    # Todo: Do this periodically in the background instead
                    # if ocpi_status == Evse.AVAILABLE:
                    #     # Let's free up the charger for the OCPI network, in case we are out of sync
                    #     close_active_sessions_for_evse(evse.uid)

                    EvseServices.send_status_updates(evse)

                    messages.success(
                        request,
                        f'You have successfully changed the EVSE status to "{evse.status}". '
                        f"Please note that the statuses in OCPP and OCPI won't always match each other "
                        f"due to differences in protocols.",
                    )
                    next_url = reverse("chargepoint-authorize")
                    messages.success(
                        request,
                        "<div>Next, you can go and "
                        f'<a href="{next_url}">authorize a Token</a> for charging.</div>',
                    )

                    return Response(
                        dict(
                            status_text="EVSE status has been changed",
                            evse=evse.uid,
                            ocpi_status=evse.status,
                            ocpp_status=ocpp_status,
                        )
                    )
                else:
                    return Response(
                        data=serializer.errors, status=status.HTTP_400_BAD_REQUEST
                    )

            # method == GET
            return Response(
                {"status_message": options_message}, status=status.HTTP_400_BAD_REQUEST
            )
        except Evse.DoesNotExist as e:
            logger.exception("Evse does not exists")
            evse_admin = reverse("admin:ocpi22_evse_changelist")
            messages.info(
                request,
                "Seems that the EVSE you specified does not exist. You can "
                f'check <a target="evseadmin" href="{evse_admin}">the list of known EVSEs</a> '
                "using the admin tools.",
            )
            return Response(dict(status_text=str(e)), status=status.HTTP_404_NOT_FOUND)

    @action(methods=("GET", "POST"), detail=False)
    def authorize(self, request):
        """
        Authorize a charging session using a specific RFID token. Call this when the driver has tapped an RFID
        which is not known to your Charge Point Management System.

        {{flowchart}}

        **NOTE**: Authorization responses from MSPs are cached for 15 minutes, so feel free to
        call this endpoint multiple times when preparing to start a charging session.

        ## Status Codes

        * `HTTP_200_OK` when the RFID tag was authorized for charging
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_401_UNAUTHORIZED` when the RFID tag exists, but is not valid for charging at the moment
        * `HTTP_404_NOT_FOUND` when the RFID tag does not exist
        """
        try:
            if request.method == "POST":
                data = dict(
                    allowed=AuthorizationEnum.NOT_ALLOWED,
                    token="",
                    responding_party="*",
                    billed_to="*",
                    authorization_reference=None,
                    auth_method="AUTH_REQUEST",
                    session_id=None,
                )
                serializer = AuthorizationSerializer(data=request.data)
                if serializer.is_valid():
                    next_url = reverse("chargepoint-start-transaction")

                    evse: Evse = serializer.validated_data.get("evse")
                    token: Union[Token, AdhocToken, str] = (
                        serializer.validated_data.get("token")
                    )
                    token_uid = get_token_id(token)
                    data["token"] = token_uid
                    session = get_session_by_token_uid_and_evse_uid(
                        token_uid, evse.uid, max_age_minutes=15
                    )
                    if session:
                        ocpi_logging.info(
                            f"Pre-existing Session **{markdown_escape(session.uid)}** "
                            f"with authorization **{markdown_escape(session.authorization_reference)}**",
                            request=request,
                        )
                        messages.success(
                            request,
                            f"This Token, **{markdown_escape(str(token_uid))}** has been authorized "
                            f"earlier by **{markdown_escape(str(session.billed_to))}** and the "
                            f"authorization was cached in the system.",
                        )
                        authorization = get_token_authorization_from_session(session)
                    else:
                        _authorize_token.clear_cache_item(
                            token, evse.location, request=request, evse_id=evse.evse_id
                        )
                        authorization: TokenAuthorization = authorize_token(
                            token, evse.location, request=request, evse_id=evse.evse_id
                        )

                    if (
                        not authorization
                        or authorization.allowed != AuthorizationEnum.ALLOWED
                    ):
                        session = None
                        token_admin = reverse("admin:ocpi22_token_changelist")
                        messages.error(
                            request,
                            f'The response was "{authorization.allowed if authorization else "N/A"}" for the Token "{token}".',
                        )
                        messages.info(
                            request,
                            f'You can <a target="tokenadmin" href="{token_admin}">browse the list of '
                            "known Tokens in our database</a> or try one which an MSP has in their database.",
                        )
                    else:
                        token_dict = authorization.token
                        ad_hoc_token = AdhocToken(
                            uid=token_dict.get("uid"),
                            valid=token_dict.get("valid"),
                            billed_to=authorization.get_token_party(),
                            type=token_dict.get("type"),
                            ocpi_master=authorization.msp,
                            contract_id=authorization.token.get("contract_id", "-"),
                        )
                        route_through = get_credentialsrole(
                            party=Party.from_str(authorization.responding_party)
                        )
                        if not route_through:
                            raise ValueError(
                                f"CredentialsRole for {authorization.responding_party} not found in the database."
                            )
                        if not session:
                            session = create_session(
                                credentials=route_through.credentials,
                                authorization_reference=authorization.authorization_reference,
                                authorization_method=authorization.auth_method,
                                billed_to=authorization.msp,
                                ad_hoc_token=ad_hoc_token,
                                evse_uid=evse.uid,
                                connector_id=None,
                                location_id=evse.location.uid,
                                hub_session_id=authorization.hub_session_id,
                            )
                            save_to_session_cache(
                                route=find_route_from_credentials(
                                    route_through.credentials, OcpiModuleEnum.SESSIONS
                                ),
                                session=session,
                            )
                            messages.success(
                                request,
                                "A new OCPI Session has been started in `PENDING` status. "
                                f"Store the Session ID, **{markdown_escape(session.uid)}**. "
                                "You will need it for `meter_values` and `stop_session`. Next, you can "
                                f'<a href="{next_url}">start the charging session</a>. '
                                f"Make sure to use the Token **{get_token_id(token)}**, "
                                f"which has been authorized. The authorization expires in 15 minutes.",
                            )

                    if authorization:
                        data = dict(
                            allowed=authorization.allowed,
                            token=authorization.token.get("uid"),
                            responding_party=authorization.responding_party,
                            billed_to=authorization.billed_to,
                            authorization_reference=authorization.authorization_reference,
                            auth_method=authorization.auth_method,
                            session_id=session.uid if session else None,
                        )
                    serializer = CPOAuthorizationResponseSerializer(instance=data)
                    return Response(
                        serializer.data,
                        status=authorization.get_http_status()
                        if authorization
                        else 401,
                    )
                else:
                    return Response(
                        data=serializer.errors, status=status.HTTP_400_BAD_REQUEST
                    )

            # method == GET
            return Response(
                {"status_message": options_message}, status=status.HTTP_400_BAD_REQUEST
            )

        except (ObjectDoesNotExist, ValueError, OSError) as e:
            logger.exception("Exception in CPO authorize()", extra={"error": str(e)})
            evse_admin = reverse("admin:ocpi22_evse_changelist")
            token_admin = reverse("admin:ocpi22_token_changelist")
            messages.info(
                request,
                "Seems that the ID for the EVSE or the Token was not quite correct. You can "
                f'check <a target="evseadmin" href="{evse_admin}">the list of known EVSEs</a> '
                f'and <a target="tokenadmin" href="{token_admin}">the list of known Tokens</a> '
                f"using the admin tools. Error message: '{e}'",
            )
            return Response(
                dict(status_message=str(e)), status=status.HTTP_404_NOT_FOUND
            )

    @action(methods=("GET", "POST"), detail=False)
    def start_transaction(self, request):
        """
        This call starts the charging transaction (which equals the OCPI session in the roaming network).

        {{flowchart}}

        ## Energy
        If your charge point doesn't reset its energy meter between charging sessions,
        set start_kwh to the current meter value at the start of the session.

        ## Charger Status
        Please update the status to `CHARGING` by using [chargepoint-status-change]. This way
        we will be able to show the real availability status to the driver.

        ## Status Codes
        * `HTTP_200_OK` when the charging session was started successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_401_UNAUTHORIZED` when the APP_USER token has expired
        * `HTTP_404_NOT_FOUND` when the Token or the EVSE doesn't exist
        """
        try:
            next_url = reverse("chargepoint-meter-values")

            if request.method == "POST":
                logger.info(
                    f"Debugging: start_transaction incoming data before serializer: {request.data}"
                )
                serializer = StartTransactionSerializer(
                    data=request.data,
                    context={"version": request.version, "request": request},
                )
                if serializer.is_valid():
                    session = serializer.validated_data["session"]
                    connector_id: str = serializer.validated_data["connector_id"]
                    session.start_kwh = serializer.validated_data["start_kwh"]
                    session.stop_kwh = session.start_kwh
                    session_service = SessionService()
                    if session.auth_method == enum.AuthMethodChoices.COMMAND:
                        session_service.start_command_session(
                            session=session,
                            start_kwh=session.start_kwh,
                        )
                        session.send_updates()
                        session_serializer = CpoSessionSerializer(
                            instance=session,
                            context={"version": request.version, "request": request},
                        )
                        return Response(session_serializer.data)

                    # For AUTH_REQUEST and WHITELIST methods, perform full transaction start
                    # TODO Reject authorization for stale authorizations
                    authorization: TokenAuthorization = (
                        get_token_authorization_from_session(session)
                    )

                    if not authorization:
                        return Response(
                            dict(
                                status_text="Token is (no longer) valid",
                                token_id=session.cdr_token.uid,
                            ),
                            status=status.HTTP_401_UNAUTHORIZED,
                        )
                    session_service.set_currency_and_start(
                        session=session, connector_id=connector_id
                    )
                    session.send_updates(update_type=ChargingNotificationType.Start)

                    messages.info(
                        request,
                        {
                            enum.AuthMethodChoices.COMMAND: "This Session is based on an authorization which was "
                            f"implied when receiving the remote command from MSP {session.billed_to}.",
                            enum.AuthMethodChoices.AUTH_REQUEST: f"This Session was authorized by {session.billed_to}.",
                            enum.AuthMethodChoices.WHITELIST: "No authorization was requested from an MSP, because the Token "
                            "is whitelisted and hence no authorization is to be done.",
                        }.get(session.auth_method, ""),
                    )
                    messages.success(
                        request,
                        "<div>Next, you can go and send some "
                        f'<a href="{next_url}">meter values</a>.</div>',
                    )

                    session_serializer = CpoSessionSerializer(
                        instance=session,
                        context={"version": request.version, "request": request},
                    )
                    return Response(session_serializer.data)
                else:
                    messages.error(
                        request,
                        "Unable to start the session you requested, "
                        "please check that the parameters are as required. "
                        'You can find the schema by pressing "OPTIONS".',
                    )
                    return Response(
                        data=serializer.errors, status=status.HTTP_400_BAD_REQUEST
                    )

            # method == GET
            return Response(
                {"status_message": options_message}, status=status.HTTP_400_BAD_REQUEST
            )

        except ObjectDoesNotExist as e:
            logger.error(f"Exception in start_transaction(): {e}")
            return Response(dict(status=str(e)), status=status.HTTP_404_NOT_FOUND)
        except EvseOccupied as e:
            stop_transaction_url = reverse("chargepoint-stop-transaction")
            status_change_url = reverse("chargepoint-status-change")
            messages.error(
                request,
                f"{e} You can complete active sessions using the "
                f'<a href="{stop_transaction_url}">stop_transaction</a> or by '
                f'<a href="{status_change_url}">changing the EVSE status</a> to "AVAILABLE".',
            )
            return Response(dict(status=str(e)), status=status.HTTP_409_CONFLICT)

    @action(methods=("GET", "POST"), detail=False)
    def meter_values(self, request):
        """
        Update the session progress, so that the MSP can inform their end user about the status
        and kWh of the current charging session. This endpoint should be called at least once per minute with the
        up to date information about the ongoing charging session, preferably every 10-15 seconds.

        {{flowchart}}

        ## Status Codes
        * `HTTP_200_OK` when the session was updated with the provided meter values
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_403_FORBIDDEN` when the session is not active
        * `HTTP_404_NOT_FOUND` when the session doesn't exist
        * `HTTP_409_CONFLICT` when the applicable Tariff is misconfigured

        ## Energy
        The used energy is calculated by `kwh - start_kwh` (given in `start_transaction`).

        """
        try:
            if request.method == "POST":
                serializer = MeterValuesSerializer(
                    data=request.data,
                    context={"version": request.version, "request": request},
                )
                if serializer.is_valid():
                    return process_meter_values(request, **serializer.validated_data)
                else:
                    return Response(
                        data=serializer.errors, status=status.HTTP_400_BAD_REQUEST
                    )

            # method == GET
            return Response(
                {"status_message": options_message}, status=status.HTTP_400_BAD_REQUEST
            )

        except ObjectDoesNotExist as e:
            return Response(dict(status=str(e)), status=status.HTTP_404_NOT_FOUND)
        except (ValidationError, RuntimeError) as e:
            logger.error(f"Exception in meter_values(): {e}")
            return Response(dict(status=str(e)), status=status.HTTP_409_CONFLICT)

    @action(methods=("GET", "POST"), detail=False)
    def stop_transaction(self, request):
        """
        This call will end the OCPI Session. Call it after the cable has been disconnected from the vehicle.

        {{flowchart}}

        ## Energy
        The used energy is calculated by `stop_kwh - start_kwh`
        (`start_kwh` was given in `start_transaction`).

        ## Charger Status
        Please update the status by using the [chargepoint-status-change].

        ## Status Codes
        * `HTTP_200_OK` when the session was finished and Charge Detail Record was created successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_404_NOT_FOUND` when the Session doesn't exist
        * `HTTP_409_CONFLICT` when the Session has already been finished earlier
        """
        try:
            if request.method == "POST":
                serializer = StopTransactionSerializer(
                    data=request.data,
                    context={"version": request.version, "request": request},
                )
                if serializer.is_valid():
                    session = serializer.validated_data["session"]
                    stop_kwh = serializer.validated_data.get("stop_kwh")
                    stop_timestamp = serializer.validated_data.get("timestamp")
                    if session.is_final():
                        return Response(
                            dict(
                                status_text="Session was completed earlier, cannot stop it twice"
                            ),
                            status=status.HTTP_409_CONFLICT,
                        )
                    SessionService().stop_and_create_cdr(
                        session=session, stop_kwh=stop_kwh, timestamp=stop_timestamp
                    )
                    session.send_updates(update_type=ChargingNotificationType.End)

                    extra_information = {
                        enum.AuthMethodChoices.COMMAND: "<div>This session was started by using the MSP mobile application, "
                        "but the flow is mostly the same with RFID token charging.</div>",
                        enum.AuthMethodChoices.AUTH_REQUEST: "<div>This session was started by using an RFID token, "
                        "but the flow is mostly the same when the driver starts the charging session "
                        "using an MSP mobile application.</div>",
                    }.get(session.auth_method, "")

                    messages.success(
                        request,
                        f"You have concluded the OCPI Session **{markdown_escape(session.uid)}** "
                        f"with {session.kwh} kWh. At this point, the OCPI Charge Detail Record is "
                        f"created automatically, and if you have set your URL for the "
                        f"invoicing webhook, the CDR is sent to the webhook. "
                        f"{extra_information}",
                    )

                    session_serializer = CpoSessionSerializer(
                        instance=session,
                        context={"version": request.version, "request": request},
                    )
                    return Response(session_serializer.data)
                else:
                    return Response(
                        data=serializer.errors, status=status.HTTP_400_BAD_REQUEST
                    )

            # method == GET
            return Response(
                {"status_message": options_message}, status=status.HTTP_400_BAD_REQUEST
            )

        except ObjectDoesNotExist as e:
            logger.error(f"Exception in stop_transaction(): {e}")
            return Response(dict(status=str(e)), status=status.HTTP_404_NOT_FOUND)

    @ocpi_exception_handler
    @action(
        methods=("GET", "POST"),
        detail=False,
        url_path="remote_command_result(?:/(?P<command_id>[^/.]+))?",
    )
    def remote_command_result(self, request, command_id=None):
        """
        Using this endpoint you indicate the success of the requested remote command.
        You'll need the command_id in the URL, so you must use the exact response_url you get when
        we call your start_transaction callback.

        {{flowchart}}

        ## Status Codes
        * `HTTP_200_OK` when the call was succesful
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way

        """
        try:
            if request.method == "GET":
                return Response(
                    {"status_message": options_message},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            command = command_store[command_id]
            assert command, "Unable to find the remote command in question"

            if request.method == "POST":
                serializer = CpoCommandResultSerializer(
                    data=request.data,
                    context={"version": request.version, "request": request},
                )
                if serializer.is_valid():
                    token_element = command.get("token") or command.get("ad_hoc_token")
                    token_id = token_element.get("uid") if token_element else ""
                    session = get_session_by_token_uid(token_id, max_age_minutes=15)
                    if not session:
                        return Response(
                            dict(
                                status_text="Session not found",
                                token_id=token_id,
                                authorization_reference=command[
                                    "authorization_reference"
                                ],
                            ),
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    result = serializer.validated_data.get("result")
                    if result == CpoCommandResultSerializer.ACCEPTED:
                        message = MessageTexts.get("PREPARING_TO_CHARGE")
                    else:
                        message = MessageTexts.get(
                            result, MessageTexts.get("DEFAULT_CHARGER_ERROR_TEXT")
                        )
                    params = dict(result=result, message=message)
                    ocpi_serializer = CommandResultSerializer(instance=params)
                    response_url = command.get("response_url")
                    to = party_from_str(session.billed_to)
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
                        method="post",
                        credentials_id=session.credentials.pk,
                        timeout=15,
                    )

                    # Invalidate the session in case an error has occured
                    if result != CpoCommandResultSerializer.ACCEPTED:
                        session.status = Session.INVALID
                        session.save()
                        # Update the session to MSP, but only after the CommandResult above
                        session.send_updates()

                    return Response(
                        dict(
                            status_text="Response received from eMSP",
                            token_id=token_id,
                            authorization_reference=command["authorization_reference"],
                            data=response.get("json") if response else "",
                        ),
                        status=response.get("status_code")
                        if response
                        else status.HTTP_503_SERVICE_UNAVAILABLE,
                    )
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except redis.exceptions.ConnectionError as e:
            logger.error(
                f"Cannot read and store callback settings  "
                f"due to trouble connecting with Redis: {e}",
                request=request,
            )
            return Response(
                dict(
                    status_text="Unable to store settings due to connection problem. "
                    "This is our fault, sorry. Support has been alerted."
                ),
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except KeyError:
            logger.exception(
                "Unable to find eMSP remote command from cache",
                extra={"command_id": command_id},
            )
            return Response(
                dict(
                    status_text=f"Unable to find eMSP remote command from cache, "
                    f"either the command ID (in URL) is incorrect or "
                    f"the command was issued by eMSP too long ago "
                    f"(expiration is set to {settings.REMOTE_COMMAND_EXPIRATION})"
                ),
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            f"{request.method} is not supported", status=status.HTTP_400_BAD_REQUEST
        )

    def get_view_name(self):
        if self.name:
            return f"{self.name.capitalize()}"
        return "Status Change"

    @staticmethod
    def get_object(uid=None) -> None:
        # Needed for OPTIONS to work in list view
        return None


msp_remote_commands_flowchart = dict(
    steps=(
        (
            "reserve_now_webhook",
            "Reserve Now Webhook",
            reverse_lazy("cpo-reserve-now-webhook"),
        ),
        (
            "start_transaction_webhook",
            "Start Transaction Webhook",
            reverse_lazy("cpo-start-transaction-webhook"),
        ),
        ("remote_command_result", "Remote Command Result"),
        (
            "stop_transaction_webhook",
            "Stop Transaction Webhook",
            reverse_lazy("cpo-stop-transaction-webhook"),
        ),
        (
            "invoicing_webhook",
            "Invoicing Webhook",
            reverse_lazy("cpo-invoicing-webhook"),
        ),
    ),
    process="reserve_now_webhook-->remote_command_result; start_transaction_webhook-->remote_command_result; "
    "stop_transaction_webhook-->remote_command_result; stop_transaction_webhook-->invoicing_webhook;",
)


class CpoReserveNowWebhookViewSet(WebhookViewSet):
    """
    This is where you tell the system where to send remote ReserveNow commands.
    Please see OPTIONS for details on the data fields available to the webhook,
    and the data this platform expects in response.

    {{flowchart}}

    ## URL Segments
    Example URL: `https://your.emsp.backend.server/reserve/{location_id}/{token_id}/`. The token_id will be substituted with
    the corresponding parameter from the data sent to this URL. For details, please use "OPTIONS".

    ## Basic Authentication
    Include user credentials and port in URL,
    for example `https://user:password@example.com:1234/path/to/my/endpoint/`.

    ## Status Codes

    * `HTTP_200_OK` when the webhook was set successfully
    * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
    """

    serializer_class = CPOReserveNowWebhookSerializer
    serializer = serializer_class()
    queryset = Location.objects.none()
    flowchart = msp_remote_commands_flowchart

    @action(methods=("GET", "POST", "PATCH"), detail=False, url_path="reserve_now")
    def reserve_now_webhook(self, request):
        return self.webhook(request)


class CpoStartWebhookViewSet(WebhookViewSet):
    """
    These endpoints are used for receiving remote commands from MSPs.
    Please see OPTIONS for details on the data fields available to the webhook,
    and the data this platform expects in response.

    {{flowchart}}

    ## URL Segments
    Example URL: `https://your.emsp.backend.server/start_charging/{token_id}/`. The token_id will be substituted with
    the corresponding parameter from the data sent to this URL.

    ## Basic Authentication
    Include user credentials and port in URL,
    for example `https://user:password@example.com:1234/path/to/my/endpoint/`.

    ## Status Codes
    * `HTTP_200_OK` when the webhook was set successfully
    * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
    """

    serializer_class = CPOStartWebhookSerializer
    serializer = serializer_class()
    queryset = Location.objects.none()
    flowchart = msp_remote_commands_flowchart

    # cpo-start-transaction-webhook
    @action(
        methods=("GET", "POST", "PATCH"),
        detail=False,
        url_path="start_transaction",
        url_name="transaction-webhook",
    )
    def start_transaction_webhook(self, request):
        return self.webhook(request)


class CpoStopWebhookViewSet(WebhookViewSet):
    """
    These endpoints are used for receiving remote commands from MSPs.
    Please see OPTIONS for details on the data fields available to the webhook,
    and the data this platform expects in response.

    {{flowchart}}

    ## URL Segments
    Example URL: `https://your.emsp.backend.server/stop_charging/{token_id}/`. The token_id will be substituted with
    the corresponding parameter from the data sent to this URL. For details, please use "OPTIONS".

    ## Basic Authentication
    Include user credentials and port in URL,
    for example `https://user:password@example.com:1234/path/to/my/endpoint/`.

    ## Status Codes
    * `HTTP_200_OK` when the webhook was set successfully
    * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
    """

    serializer_class = CPOStopWebhookSerializer
    serializer = serializer_class()
    queryset = Location.objects.none()
    flowchart = msp_remote_commands_flowchart

    # cpo-stop-transaction-webhook
    @action(
        methods=("GET", "POST", "PATCH"),
        detail=False,
        url_path="stop_transaction",
        url_name="transaction-webhook",
    )
    def stop_transaction_webhook(self, request):
        return self.webhook(request)


class InvoiceWebhookViewSet(WebhookViewSet):
    """
    This webhook will receive the invoicing data (Charge Detail Records).
    Please see OPTIONS for details on the data fields available to the webhook,
    and the data this platform expects in response.

    {{flowchart}}

    ## URL Segments
    Example URL: `https://your.emsp.backend.server/session/{session_id}/`. The session_id will be substituted with
    the corresponding parameter from the data sent to this URL. For details, please use "OPTIONS".

    ## Basic Authentication
    Include user credentials and port in URL,
    for example `https://user:password@example.com:1234/path/to/my/endpoint/`.

    ## Status Codes
    * `HTTP_200_OK` when the webhook was set successfully
    * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
    """

    serializer_class = InvoicingCallbackSerializer
    serializer = serializer_class()
    queryset = Session.objects.none()
    flowchart = msp_remote_commands_flowchart

    # cpo-invoicing-webhook
    @action(
        methods=("GET", "POST", "PATCH"),
        detail=False,
        url_path="invoice",
        url_name="webhook",
    )
    def invoicing_webhook(self, request):
        return self.webhook(request)


class ChargePointOperatorAPIView(routers.APIRootView):
    """
    This is the ChargerHub.EU roaming API for CPOs.
    By using these simple endpoints, you can connect your existing
    backend to roaming partners without the need to implement the full OCPI protocol.

    **For more details on the individual endpoints, click the flow nodes or the links below,
    and you will find the step-by-step technical documentation.**

    # Flows

    ## Charging Process Using an RFID
    {{rfid_charging_flowchart}}

    ## Charging Process Using a Mobile or a Web App
    {{app_charging_flowchart}}
    """

    def get_view_description(self, html=False):
        shorthand = [
            ("{{rfid_charging_flowchart}}", ChargePointViewSet().get_flowchart()),
            ("{{app_charging_flowchart}}", CpoStartWebhookViewSet().get_flowchart()),
        ]
        result = reduce(
            lambda a, kv: a.replace(*kv), shorthand, super().get_view_description(html)
        )
        return mark_safe(result)

    @method_decorator(login_required)
    def get(self, request, *args, **kwargs):
        """
        Compile the example URLs for the root page
        """

        result = dict(
            status_management=dict(
                status_change=request.build_absolute_uri(
                    reverse("chargepoint-status-change")
                )
            ),
            location_management=dict(
                tariffs=request.build_absolute_uri(reverse("solid-tariff-list")),
            ),
            charging_session=dict(
                authorize=request.build_absolute_uri(reverse("chargepoint-authorize")),
                start_transaction=request.build_absolute_uri(
                    reverse("chargepoint-start-transaction")
                ),
                meter_values=request.build_absolute_uri(
                    reverse("chargepoint-meter-values")
                ),
                stop_transaction=request.build_absolute_uri(
                    reverse("chargepoint-stop-transaction")
                ),
            ),
            webhooks=dict(
                remote_commands=dict(
                    reserve_now=request.build_absolute_uri(
                        reverse("cpo-reserve-now-webhook")
                    ),
                    start_transaction=request.build_absolute_uri(
                        reverse("cpo-start-transaction-webhook")
                    ),
                    stop_transaction=request.build_absolute_uri(
                        reverse("cpo-stop-transaction-webhook")
                    ),
                    remote_command_result=request.build_absolute_uri(
                        reverse("chargepoint-remote-command-result")
                    ),
                ),
                invoice=request.build_absolute_uri(reverse("cpo-invoicing-webhook")),
            ),
            reports=dict(
                summary=request.build_absolute_uri(reverse("billing-summary")),
                list=request.build_absolute_uri(reverse("billing-list")),
            ),
        )
        return Response(result)

    def get_view_name(self):
        return "Charge Point Operator API"


class CPORouter(routers.DefaultRouter):
    APIRootView = ChargePointOperatorAPIView
    root_view_name = "cpo-api"


@receiver(post_save, sender=Cdr)
def cdr_post_save(sender, instance: Cdr, created, *_args, raw, **_kwargs):
    if raw:
        return
    try:
        if settings.ENV != "test":
            cdr_serializer = CdrSerializer(instance)
            send_to_webhook_legacy(
                serialized_data=cdr_serializer.data,
                serializer=InvoicingCallbackSerializer,
            )
    except Exception as e:
        logger.error(f"Unable to send the new CDR to CpoInvoiceWebhook: {e}")


api = CustomNinjaAPI(
    auth=NinjaBasicAuth(),
    urls_namespace="cpo",
    title="CPO API",
)
location_service = LocationService()


@api.put(
    "/",
    response={200: LocationIn, 201: LocationIn, 403: Error, 400: Error},
    tags=["Location"],
)
def update_location(request, location: LocationIn):
    our_credentials_role = get_our_credentialsrole(role=OcpiRolesEnum.CPO)
    if (
        not our_credentials_role.party_str()
        == f"{location.country_code}*{location.party_id}"
    ):
        raise HttpError(
            403, f"{location.country_code}*{location.party_id} party is not allowed."
        )
    existing_location: Location = Location.get_if_exists(
        uid__iexact=location.uid, ocpi_master=our_credentials_role
    )
    try:
        if existing_location:
            saved_location = location_service.update_location(
                location, our_credentials_role, existing_location
            )
            status_code = status.HTTP_200_OK
        else:
            saved_location = location_service.create_location(
                location, our_credentials_role
            )
            status_code = status.HTTP_201_CREATED

        return status_code, LocationIn.from_orm(saved_location)
    except ValidationError as e:
        return 400, Error(message=str(e.detail))
