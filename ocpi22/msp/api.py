import json
from functools import reduce

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.safestring import mark_safe

import ocpi22.ocpi_logging as logging
from decimal import Decimal

import requests
from django.conf import settings
from django.utils.translation import get_language, gettext as _
from rest_framework import routers, status, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAdminUser

from ocpi22.cpo.api import InvoiceWebhookViewSet
from ocpi22.models.cdr import Cdr
from ocpi22.util import StandardResultsSetPagination
from ocpi22.viewsets import FlowchartViewSet
from util import reverse, ErrorLoggingResponse as Response, get_message_by_language
from rest_framework.viewsets import GenericViewSet

from ocpi22.choices import OcpiRolesEnum
from ocpi22.commands.commands import (
    send_start_command,
    send_stop_command,
    send_reserve_command,
)
from ocpi22.commands.serializers import CommandResultSerializer
from ocpi22.cpo.serializers import SolidTariffSerializer
from ocpi22.ocpi.serializers import InvoicingCallbackSerializer, CdrSerializer
from ocpi22.generic_views import WebhookViewSet
from ocpi22.messages import messages
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session
from ocpi22.models.tariff import Tariff
from ocpi22.models.token import Token
from ocpi22.msp.account import Account
from ocpi22.msp.models import Authorization
from ocpi22.msp.serializers import (
    StartChargingSerializer,
    StopChargingSerializer,
    SessionStatusSerializer,
    MspSessionSerializer,
    MSPAuthorizeCallbackSerializer,
    ReserveSerializer,
    MSPChargePointStatusCallbackSerializer,
    MSPSessionCallbackSerializer,
)
from ocpi22.ocpi.api import TokenViewSet
from ocpi22.ocpi.util import OCPIResponse, generate_auth_reference
from ocpi22.sessions.util import get_session
from ocpi22.tokens.util import construct_adhoc_token

from ocpiconnector.ocpi_identities import get_our_party

# Todo: Handle gracefully situation where CPO backend is offline (now 503)

# Todo: limit access to certain privilege holders


def _language_response(response):
    try:
        data = response.json()
        data = data.get("data", data) or data
        message = data.get("message")
    except Exception as e:
        logging.error(
            f"Got a problematic message in response ({e}): {response.text[:500]}"
        )
        data = {}
        message = None

    if message:
        data.update(
            message_display=get_message_by_language(data.get("message"), get_language())
        )
    else:
        data.update(message_display=data.get("status_message"))
    return Response(data, status=response.status_code)


def process_start_charging(
    request,
    serializer,
    location,
    evse,
    connector_id: str = None,
    contract_id: str = "",
    max_price: Decimal = None,
    token_id: str = None,
):
    if token_id:
        # Using an external user database
        permission_required = "ocpi22.charge_with_any_token"
        user: User = request.user
        if user.has_perm(permission_required) and not user.is_superuser:
            return Response(
                data=dict(
                    error_message=f"It seems that you are attempting to use an external user database. "
                    f"To specify a token_id, the user account you use in your API calls needs to have "
                    f"the {permission_required} permission set"
                ),
                status=status.HTTP_403_FORBIDDEN,
            )
        token = construct_adhoc_token(token_id, contract_id)
    else:
        # Using the user database we provide
        account = request.user.accounts.first() or Account.create(request.user)
        if (
            not max_price
            and settings.REQUIRE_WALLET_BALANCE
            and account.balance <= Decimal("2.0")
        ):
            return Response(
                dict(
                    status_message="There is not enough balance in the account to start charging"
                ),
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )
        token = construct_adhoc_token(account.app_token_id, contract_id)

    authorization_reference = generate_auth_reference()

    response: requests.Response = send_start_command(
        request, evse, token, connector_id, contract_id, authorization_reference
    )
    Authorization.objects.create(
        authorization_reference=authorization_reference,
        max_price=max_price,
        token_uid=token.uid,
    )
    if response.status_code == status.HTTP_200_OK:
        messages.success(
            request,
            "You have gotten a positive response from the CPO. "
            "Next the CPO backend system will check if the charger "
            "can actually start a charging session. If everything is ok, "
            "you will receive a Session object followed by Session updates "
            "with an updated kWh measurement.",
        )
        session_status_url = reverse("roaming-session-status")
        notes = ""
        if token_id:
            # Instructions for using an external user database
            notes = (
                " Using the token_id field means that you are using your own user database. "
                "Therefore, when checking session status using "
                f'<a class="alert-link" href="{session_status_url}">the Session status URL</a>, '
                f"you need to use the <b>token_id ({token_id})</b> parameter instead of a session_id."
            )
        webhook_url = reverse("msp-session-webhook")
        messages.info(
            request,
            mark_safe(
                "Next, you can go and "
                f'<a class="alert-link" href="{session_status_url}">check the Session status</a>, '
                "if it is already available. A more efficient solution is to "
                f'<a class="alert-link" href="{webhook_url}">define a webhook URL</a> where '
                f"the Session object will be pushed when an update is received from the CPO.{notes}"
            ),
        )

    return _language_response(response)


msp_flowchart = dict(
    steps=(
        ("reserve", "Reserve", reverse_lazy("roaming-reserve")),
        (
            "status_webhook",
            "Chargepoint Status Webhook",
            reverse_lazy("msp-status-webhook"),
        ),
        ("start_charging", "Start Charging", reverse_lazy("roaming-start-charging")),
        (
            "session_status",
            "Session Status Query",
            reverse_lazy("roaming-session-status"),
        ),
        (
            "session_webhook",
            "Session Status Webhook",
            reverse_lazy("msp-session-webhook"),
        ),
        ("stop_charging", "Stop Charging", reverse_lazy("roaming-stop-charging")),
        ("invoicing_webhook", "Invoice Webhook", reverse_lazy("msp-invoicing-webhook")),
        (
            "authorize_webhook",
            "Authorize Token Webhook",
            reverse_lazy("msp-authorize-webhook"),
        ),
    ),
    process="""push_or_pull{Session<br/>update type};
            status_webhook-->reserve-->start_charging-->push_or_pull-- you pull -->session_status
            -->stop_charging-->invoicing_webhook;
            push_or_pull-- we push -->session_webhook-->stop_charging;
            authorize_webhook-->push_or_pull;
            """,
)


class MspRoamingViewSet(FlowchartViewSet):
    """ """

    queryset = Token.objects.all()
    lookup_field = "uid"
    permission_classes = [IsAdminUser]
    publicly_visible = (
        True  # Don't use the OCPI authentication, just require basic auth or OAuth2
    )
    flowchart = msp_flowchart

    def get_serializer_class(self):
        return dict(
            start_charging=StartChargingSerializer,
            session_status=SessionStatusSerializer,
            stop_charging=StopChargingSerializer,
            reserve=ReserveSerializer,
        ).get(self.action_map.get("post"), None)

    @action(methods=("GET", "POST"), detail=False)
    def reserve(self, request):
        """
        This call sends an OCPI ReserveNow command to the CPO. Reserving a charge point is optional.

        {{flowchart}}

        ## Status Codes
        * `HTTP_200_OK` when the reservation was made successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_404_NOT_FOUND` when the Token, Location or EVSE doesn't exist
        * `HTTP_422_UNPROCESSABLE_ENTITY` when the response from CPO is broken
        * `HTTP_503_SERVICE_UNAVAILABLE` when there is no network connection to the charge point
        """

        # Todo: Fail if no Tariffs for any Connector in this EVSE

        try:
            if request.method == "POST":
                serializer = ReserveSerializer(data=request.data)
                if serializer.is_valid():
                    account = request.user.accounts.first() or Account.create(
                        request.user
                    )
                    if settings.REQUIRE_WALLET_BALANCE and account.balance <= Decimal(
                        "2.0"
                    ):
                        return Response(
                            dict(
                                status_message="There is not enough balance in the account to make a reservation"
                            ),
                            status=status.HTTP_402_PAYMENT_REQUIRED,
                        )
                    location: Location = serializer.validated_data["location"]
                    evse: Evse = serializer.validated_data["evse"]
                    reservation_id: str = serializer.validated_data.get(
                        "reservation_id"
                    )
                    connector_id: str = serializer.validated_data.get("connector_id")
                    contract_id: str = serializer.validated_data.get("contract_id")
                    token = construct_adhoc_token(account.app_token_id, contract_id)
                    expiration: int = serializer.validated_data.get("expiration")
                    response: requests.Response = send_reserve_command(
                        request,
                        location,
                        evse,
                        token,
                        reservation_id,
                        connector_id,
                        contract_id,
                        expiration,
                    )
                    return _language_response(response)
                else:
                    return Response(
                        serializer.errors, status=status.HTTP_400_BAD_REQUEST
                    )

            # method == GET
            return Response(
                dict(help="Please see `OPTIONS` for the schema"),
                status=status.HTTP_400_BAD_REQUEST,
            )
        except (
            Evse.DoesNotExist,
            Token.DoesNotExist,
            Location.DoesNotExist,
            Connector.DoesNotExist,
        ) as e:
            return Response(dict(status=str(e)), status=status.HTTP_404_NOT_FOUND)
        except json.JSONDecodeError as e:
            logging.error(
                f"Cannot process start_transaction response from CPO to eMSP: {e}",
                request=request,
            )
            return Response(
                dict(status=str(e)), status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

    @action(methods=("GET", "POST"), detail=False)
    def start_charging(self, request):
        """
        This call starts the charging transaction (which equals the OCPI session in the roaming network).

        {{flowchart}}

        ## Status Codes

        * `HTTP_200_OK` when the charging session was started successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_402_PAYMENT_REQUIRED` when the user account doesn't have enough balance for charging
        (if the internal payments account functionality is configured to be in use)
        * `HTTP_404_NOT_FOUND` when the Token, Location or EVSE doesn't exist
        * `HTTP_422_UNPROCESSABLE_ENTITY` when the response from CPO is broken
        * `HTTP_503_SERVICE_UNAVAILABLE` when there is no network connection to the charge point
        """

        # Todo: Fail if no Tariffs for any Connector in this EVSE

        try:
            if request.method == "POST":
                serializer = StartChargingSerializer(
                    data=request.data, context={"request": request}
                )
                if serializer.is_valid():
                    return process_start_charging(
                        request, serializer, **serializer.validated_data
                    )
                else:
                    return Response(
                        serializer.errors, status=status.HTTP_400_BAD_REQUEST
                    )

            # method == GET
            return Response(
                dict(help="Please see `OPTIONS` for the schema"),
                status=status.HTTP_400_BAD_REQUEST,
            )
        except (
            Evse.DoesNotExist,
            Token.DoesNotExist,
            Location.DoesNotExist,
            Connector.DoesNotExist,
        ) as e:
            logging.error(
                f"Trying to start charging on a nonexistent Location, EVSE or Token: {e}",
                request,
            )
            return Response(dict(status=str(e)), status=status.HTTP_404_NOT_FOUND)
        except json.JSONDecodeError as e:
            logging.error(
                f"Cannot process start_transaction response from CPO to eMSP: {e}",
                request=request,
            )
            return Response(
                dict(status=str(e)), status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

    @action(methods=("GET", "POST"), detail=False)
    def session_status(self, request):
        """
        Poll the status of the ongoing session for this user.
        For performance reasons, please use the [msp-session-webhook]
        to receive push messages instead of polling at regular intervals.

        {{flowchart}}

        NOTE: If you are using the User management system of this platform, only one session at a time is supported.

        ## Status Codes

        * `HTTP_200_OK` when the charging session is ongoing and status is available
        * `HTTP_404_NOT_FOUND` when the Session doesn't exist or status is not yet available
        """
        try:
            serializer = SessionStatusSerializer(
                data=request.data, context={"request": request}
            )
            if serializer.is_valid():
                session = serializer.validated_data.get("session")
                token_id = serializer.validated_data.get("token_id")
                if session and token_id:
                    return Response(
                        dict(
                            status="You should specify either Session or Token ID, but not both"
                        ),
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if not session and not token_id:
                    return Response(
                        dict(
                            status="Please specify either Session or Token ID to get the Session status"
                        ),
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if not session:
                    # Can we find the session by token? Check if we have authorized a Session
                    authorization = (
                        Authorization.objects.filter(token_uid=token_id)
                        .order_by("-created")
                        .first()
                    )
                    if authorization:
                        session = authorization.session
                        if not session:
                            return Response(
                                dict(
                                    status_text="Session starting",
                                    session=dict(
                                        status=Session.PENDING,
                                        display_status=_("Pending"),
                                        session_id=_("N/A"),
                                        token=dict(
                                            token_id=token_id,
                                            type="APP_USER",
                                            contract_id="N/A",
                                        ),
                                    ),
                                ),
                                status=status.HTTP_200_OK,
                            )
                    else:
                        return Response(
                            dict(status_text="Session not found"),
                            status=status.HTTP_404_NOT_FOUND,
                        )
                data = MspSessionSerializer(instance=session).data
                ocpi_messages = data.get("message")
                if ocpi_messages:
                    data.update(
                        message_display=get_message_by_language(
                            ocpi_messages, get_language()
                        )
                    )
                return Response(data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except (Evse.DoesNotExist, Token.DoesNotExist) as e:
            return Response(dict(status=str(e)), status=status.HTTP_404_NOT_FOUND)

    @action(methods=("GET", "POST"), detail=False)
    def stop_charging(self, request):
        """
        This call stops the charging transaction.

        {{flowchart}}

        ## Status Codes

        * `HTTP_200_OK` when the charging session was stopped successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_404_NOT_FOUND` when the Token or the EVSE doesn't exist
        * `HTTP_422_UNPROCESSABLE_ENTITY` when the response from CPO is broken
        """
        try:
            if request.method == "POST":
                serializer = StopChargingSerializer(
                    data=request.data, context={"request": request}
                )
                if serializer.is_valid():
                    session = serializer.validated_data.get("session")
                    token_id = serializer.validated_data.get("token_id")
                    if session and token_id:
                        return Response(
                            dict(
                                status="You should specify either Session or Token ID, but not both"
                            ),
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    if not session:
                        token_id = (
                            token_id or request.user.accounts.first().app_token_id
                        )
                        session = get_session(token_id)
                        if not session:
                            return Response(
                                dict(
                                    status=f"No active session found for token `{token_id}`. "
                                    f"There may not have been a Session update from CPO."
                                ),
                                status=status.HTTP_404_NOT_FOUND,
                            )
                    response: requests.Response = send_stop_command(session)
                    return _language_response(response)
                else:
                    return Response(
                        serializer.errors, status=status.HTTP_400_BAD_REQUEST
                    )

            # method == GET
            return Response(
                dict(help="Please see `OPTIONS` for the schema"),
                status=status.HTTP_400_BAD_REQUEST,
            )
        except (Evse.DoesNotExist, Token.DoesNotExist) as e:
            return Response(dict(status=str(e)), status=status.HTTP_404_NOT_FOUND)
        except (json.JSONDecodeError, AttributeError, ValidationError) as e:
            logging.error(
                f"Unable to process start_transaction response from CPO to eMSP: {e}",
                request=request,
            )
            return Response(
                dict(status_message=f"Unable to process response from CPO: {e}"),
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

    def get_return_values_serializer(self):
        return dict(
            start_charging=CommandResultSerializer(),
            stop_charging=CommandResultSerializer(),
        ).get(self.action_map.get("post"))

    def get_view_name(self):
        if self.name:
            return f"{self.name.capitalize()}"
        return "Status Change"

    @staticmethod
    def get_object(uid=None) -> None:
        # Needed for OPTIONS to work in list view
        return None


class MspTokenViewSet(TokenViewSet):
    """
    **GET**: List active and inactive Tokens.

    **PUT**: Create or update a Token (usually an RFID).
    Country_code and party_id are set automatically according to your MSP identity.

    **PATCH**: Update a Token.
    """

    def check_ownership(self, token) -> bool:
        # The MSP can always update, and we force the country_code and party_id to match
        return True

    def put(
        self,
        request,
        country_code=None,
        party_id=None,
        uid=None,
        data=None,
        partial=None,
        version="2.2.1",
        **_kwargs,
    ):
        party = get_our_party(OcpiRolesEnum.EMSP)
        data = request.data
        data["country_code"] = party.country_code
        data["party_id"] = party.party_id

        result: OCPIResponse = super().put(
            request, party.country_code, party.party_id, uid, data
        )
        return Response(result.data.get("data"))

    def patch(self, request, **_kwargs):
        return self.put(request, partial=True)

    def list(self, request, *args, **kwargs):
        result: OCPIResponse = super().list(request, *args, **kwargs)
        return Response({"data": result.data.get("data")})

    def authorize(self, request, token_uid, **_kwargs):
        pass


webhooks_flowchart = dict(
    steps=(
        (
            "authorize",
            "Authorize Token Webhook",
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
            reverse_lazy("msp-invoicing-webhook"),
        ),
    ),
    process="reserve_now_webhook-->remote_command_result; start_transaction_webhook-->remote_command_result; "
    "stop_transaction_webhook-->remote_command_result; stop_transaction_webhook-->invoicing_webhook;",
)


class MspAuthorizeWebhookViewSet(WebhookViewSet):
    """
    When an RFID is tapped on a charger, this webhook will be called to authorize the token.
    Please see OPTIONS for details on the data fields available to the webhook,
    and the data this platform expects in response.

    {{flowchart}}

    ## URL Segments
    Example URL: `https://your.emsp.backend.server/authorize/{token_id}/`. The token_id will be substituted with
    the corresponding parameter from the data sent to this URL.

    ## Basic Authentication
    Include the user credentials and port of your endpoint in the URL,
    for example `https://user:password@example.com:1234/path/to/my/endpoint/`.

    ## Status Codes
    * `HTTP_200_OK` when the webhook was set successfully
    * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
    """

    serializer_class = MSPAuthorizeCallbackSerializer
    serializer = serializer_class()
    queryset = Token.objects.none()
    flowchart = msp_flowchart

    @action(methods=("GET", "POST", "PATCH"), detail=False, url_path="authorize")
    def authorize_webhook(self, request):
        return self.webhook(request)


class MspChargePointStatusWebhookViewSet(WebhookViewSet):
    """
    This is where you tell the system where to send charge point status updates.
    When a charge point changes status, the system pushes the new status to your webhook URL.
    Please see OPTIONS for details on the data fields available to the webhook,
    and the data this platform expects in response.

    {{flowchart}}

    ## URL Segments
    Example URL: `https://your.emsp.backend.server/authorize/{token_id}/`. The token_id will be substituted with
    the corresponding parameter from the data sent to this URL. For details, please use "OPTIONS".

    ## Basic Authentication
    Include the user credentials and port of your endpoint in the URL,
    for example `https://user:password@example.com:1234/path/to/my/endpoint/`.

    ## Status Codes
    * `HTTP_200_OK` when the webhook was set successfully
    * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
    """

    serializer_class = MSPChargePointStatusCallbackSerializer
    serializer = serializer_class()
    queryset = Token.objects.none()
    flowchart = msp_flowchart

    # msp-status-webhook
    @action(
        methods=("GET", "POST", "PATCH"),
        detail=False,
        url_path="status",
        url_name="webhook",
    )
    def status_webhook(self, request):
        return self.webhook(request)


class MspSessionWebhookViewSet(WebhookViewSet):
    """
    This is where you tell the system where to send Session updates.

    Please see OPTIONS for details on the data fields available to the webhook,
    and the data this platform expects in response.

    {{flowchart}}

    ## URL Segments
    Example URL: `https://your.emsp.backend.server/session/{session_id}/`. The session_id will be substituted with
    the corresponding parameter from the data sent to this URL.

    ## Basic Authentication
    Include the user credentials and port of your endpoint in the URL,
    for example `https://user:password@example.com:1234/path/to/my/endpoint/`.

    ## Status Codes
    * `HTTP_200_OK` when the webhook was set successfully
    * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
    """

    serializer_class = MSPSessionCallbackSerializer
    serializer = serializer_class()
    queryset = Session.objects.none()
    flowchart = msp_flowchart

    @action(
        methods=("GET", "POST", "PATCH"),
        detail=False,
        url_path="session",
        url_name="webhook",
    )
    def session_webhook(self, request):
        return self.webhook(request)


class MspInvoiceWebhookViewSet(InvoiceWebhookViewSet):
    """
    This is where you tell the system where to send the invoicing lines (Charge Detail Records).

    {{flowchart}}

    ## URL Segments
    Example URL: `https://your.emsp.backend.server/session/{session_id}/`. The session_id will be substituted with
    the corresponding parameter from the data sent to this URL. For details, please use "OPTIONS".

    ## Basic Authentication
    Include the user credentials and port of your endpoint in the URL,
    for example `https://user:password@example.com:1234/path/to/my/endpoint/`.

    ## Status codes
    * `HTTP_200_OK` when the webhook was set successfully
    * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
    """

    serializer_class = InvoicingCallbackSerializer
    serializer = serializer_class()
    queryset = Session.objects.none()
    flowchart = msp_flowchart

    # msp-invoicing-webhook
    @action(
        methods=("GET", "POST", "PATCH"),
        detail=False,
        url_path="invoice",
        url_name="webhook",
    )
    def invoicing_webhook(self, request):
        return self.webhook(request)


class MobilityServiceProviderAPIView(routers.APIRootView):
    """
    This is the ChargerHub.EU roaming API for MSPs.
    By using these simple endpoints, you can connect your existing
    backend to roaming partners without the need to implement the full OCPI protocol.

    ## Remote Charging Process
    {{remote_charging_flowchart}}

    For more details, click the flowchart nodes or the links below
    and you will find the step-by-step technical documentation.

    """

    metadata_class = None

    def get_view_description(self, html=False):
        shorthand = [
            ("{{remote_charging_flowchart}}", MspRoamingViewSet().get_flowchart()),
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
            charging=dict(
                reserve=request.build_absolute_uri(reverse("roaming-reserve")),
                start_charging=request.build_absolute_uri(
                    reverse("roaming-start-charging")
                ),
                session_status=request.build_absolute_uri(
                    reverse("roaming-session-status")
                ),
                stop_charging=request.build_absolute_uri(
                    reverse("roaming-stop-charging")
                ),
            ),
            data_management=dict(
                tokens=request.build_absolute_uri(
                    reverse("msp-token-list"),
                ),
            ),
            webhooks=dict(
                authorize_webhook=request.build_absolute_uri(
                    reverse("msp-authorize-webhook"),
                ),
                chargepoint_status_webhook=request.build_absolute_uri(
                    reverse("msp-status-webhook"),
                ),
                session_webhook=request.build_absolute_uri(
                    reverse("msp-session-webhook"),
                ),
                invoice=request.build_absolute_uri(reverse("msp-invoicing-webhook")),
            ),
            payment=dict(
                add_card=request.build_absolute_uri(reverse("msp-payment-add-card")),
                reserve=request.build_absolute_uri(
                    reverse("msp-payment-reserve-amount")
                ),
            ),
            billing=dict(
                cdr_list=request.build_absolute_uri(reverse("msp-cdr-list")),
                tariff_list=request.build_absolute_uri(reverse("msp-tariff-list")),
            ),
            navigation=dict(
                charge_points_geojson=request.build_absolute_uri(
                    reverse("map-locations")
                ),
                charge_points_ocpi=request.build_absolute_uri(reverse("map-ocpi")),
            ),
        )
        return Response(result)

    def get_view_name(self):
        return "eMobility Service Provider API"


class MspTariffQuickViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, GenericViewSet
):
    """
    This is the endpoint for listing tariffs with a simplified structure. If you need to view the complex
    Tariffs, use the OCPI Tariff endpoints.

    To get a single Quick Tariff, append the Tariff ID to the URL, e.g. .../T1/
    """

    queryset = Tariff.objects.all().filter(archived=False).order_by("uid")
    serializer_class = SolidTariffSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = "uid"

    def retrieve(self, request, *args, **kwargs):
        tariff = get_object_or_404(Tariff, uid=kwargs.get("uid"), archived=False)
        serializer = self.serializer_class(instance=tariff)
        return Response(serializer.data)

    @staticmethod
    def get_object(uid=None) -> Tariff:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Tariff, uid=uid)


class MSPRouter(routers.DefaultRouter):
    APIRootView = MobilityServiceProviderAPIView
    root_view_name = "msp-api"


class CdrViewSet(
    viewsets.GenericViewSet,
    viewsets.mixins.ListModelMixin,
    viewsets.mixins.RetrieveModelMixin,
):
    """
    This is the list of Charge Detail Records, which is used by the CPO for billing an MSP for charging sessions.
    You can use it for verifying the bill from the CPO.
    """

    # Todo: Limit access based on privileges set by admin

    model = Cdr
    queryset = Cdr.objects.all()
    lookup_field = "uid"
    serializer_class = CdrSerializer
    pagination_class = StandardResultsSetPagination
