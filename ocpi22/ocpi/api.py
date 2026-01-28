from logging import getLogger
from django.conf import settings
from django.db.models import ProtectedError

from typing import Optional

from django.core.handlers.wsgi import WSGIRequest
from django.views.decorators.csrf import csrf_exempt

from rest_framework import routers, status, mixins
from rest_framework.generics import get_object_or_404
from rest_framework.request import Request
from rest_framework.response import Response

from ocpi22.cpo.session_cache import get_cached_session
from ocpi22.decorators import (
    requires_sender_role,
    requires_credentialsrole,
    requires_last_updated,
)
from ocpi22.tokens.auth import authorize_token, TokenAuthorization
from ocpi22.tokens.dataclasses import TokenReference
from ocpiconnector.exception_handler import ocpi_exception_handler
from util import reverse
from rest_framework.viewsets import GenericViewSet

from ocpi22.choices import (
    MessageTexts,
    get_language,
    AuthorizationEnum,
    OcpiRolesEnum,
)
from ocpi22.commands.commands import send_stop_command
from ocpi22.msp.models import Authorization
from ocpi22.legacy_webhooks import send_to_webhook_legacy
from ocpi22.msp.serializers import (
    MSPAuthorizeCallbackSerializer,
    MSPSessionCallbackSerializer,
)
from ocpi22.ocpi.serializers import (
    TokenSerializer,
    TariffSerializer,
    CdrSerializer,
    CredentialsSerializer,
    SessionSerializer,
    ClientInfoSerializer,
)
from ocpi22.models.credentials import (
    Credentials,
    CredentialsRole,
    store_endpoints_for_party,
)
from ocpi22.models.location import Location
from ocpi22.models.tariff import Tariff
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.models.cdr import Cdr
from ocpi22.util import (
    OCPIVersioning,
    OCPIListModelMixin,
    generate_random_token,
    build_absolute_uri,
)
from ocpi22.ocpi.util import (
    OCPIBadRequestResponse,
    OCPINotOwnerResponse,
    OCPIResponse,
    Ocpi,
    OCPIPaginationAndHeaders,
    generate_auth_reference,
    OCPIUrlParametersRequiredResponse,
)
from ocpi22.credentials.versions import get_endpoints_dict
from ocpiconnector.management.commands.exchange_credentials import (
    get_our_roles,
    select_version,
    get_endpoints,
)
from ocpiconnector.ocpi_identities import (
    ocpi_platform,
    get_our_credentialsrole,
)

logger = getLogger(__name__)

# Todo: In case a PATCH request fails, the client is expected to call the GET method to check the state
#  of the object in the other party’s system. If the object doesn’t exist, the client should do a PUT.


def make_ocpi_response(authorization: TokenAuthorization) -> OCPIResponse:
    # Do not return an HTTP error if OCPI message is intact (except for nonexistent Tokens)
    ocpi_status = dict(
        ALLOWED=Ocpi.OK,
        BLOCKED=Ocpi.OK,
        EXPIRED=Ocpi.OK,
        NO_CREDIT=Ocpi.OK,
        NOT_ALLOWED=Ocpi.OK,
    ).get(authorization.allowed, Ocpi.ServerError.GENERIC_SERVER_ERROR)
    http_status = status.HTTP_200_OK
    status_message = authorization.get_status_message()

    return OCPIResponse(
        dict(
            allowed=authorization.allowed,
            token=authorization.token,
            authorization_reference=authorization.authorization_reference,
        ),
        status_code=ocpi_status,
        status=http_status,
        status_message=status_message,
    )


class TokenViewSet(OCPIListModelMixin, GenericViewSet):
    serializer_class = TokenSerializer
    pagination_class = OCPIPaginationAndHeaders
    versioning_class = OCPIVersioning
    lookup_field = "uid"

    def get_view_name(self):
        if hasattr(self, "kwargs") and "uid" in self.kwargs:
            return f'Token {self.kwargs.get("uid")}'
        if self.name:
            return f"{self.name.capitalize()}"
        return "Tokens"

    def get_queryset(self):
        return Token.objects.partner_filter(self.request).order_by("created")

    @ocpi_exception_handler
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @staticmethod
    def get_object(uid=None) -> Optional[Token]:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Token, uid=uid)

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.EMSP)
    @requires_credentialsrole
    def put(
        self,
        request,
        country_code=None,
        party_id=None,
        uid=None,
        data=None,
        patch=False,
        version="2.2.1",
        credentialsrole=None,
    ) -> OCPIResponse:
        if request and not request.party_specified_in_url:
            return OCPIUrlParametersRequiredResponse("token")

        uid = uid or data.get("uid")
        return self.save_or_update(request, data, credentialsrole, uid, patch, version)

    @staticmethod
    def save_or_update(
        request, data, credentialsrole, uid, patch=False, version="2.2.1"
    ) -> OCPIResponse:
        assert uid, "UID is a required parameter for TokenViewSet.save_or_update()"
        token: Token = Token.get_if_exists(uid__iexact=uid, ocpi_master=credentialsrole)
        created = bool(not token)
        serializer = TokenSerializer(
            data=data, instance=token, partial=patch, context={"version": version}
        )
        if serializer.is_valid():
            created_token = serializer.save(ocpi_master=credentialsrole)
            logger.info(f'{"Creating" if created else "Updating"} {created_token}')
            created_token.post_process_after_update_or_create()
            created_token.send_hub_updates()
            return OCPIResponse(
                serializer.data,
                http_status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            )
        return OCPIResponse(
            errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST
        )

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.EMSP)
    @requires_last_updated
    def patch(self, *args, **kwargs):
        return self.put(*args, patch=True, **kwargs)

    @ocpi_exception_handler
    @csrf_exempt
    def authorize(self, request: Request, token_uid: str, **kwargs) -> OCPIResponse:
        info = None
        user_language = "en"
        max_price = None
        location: Optional[Location] = None

        try:
            if ocpi_platform.is_hub:
                return self.hub_authorize(request, token_uid, location)
            token: Token = Token.get_if_exists(
                uid__iexact=token_uid,
                ocpi_master=get_our_credentialsrole(OcpiRolesEnum.EMSP),
            )
            if not token and not ocpi_platform.is_hub:
                # OCPI 2.2: If the token is not known, the response SHALL contain the status code:
                # 2004: Unknown Token, and no data field.
                return OCPIResponse(
                    status_code=Ocpi.ClientError.UNKNOWN_TOKEN,
                    status=status.HTTP_404_NOT_FOUND,
                    status_message=f'Unknown Token "{token_uid}"',
                )

            logger.info(
                f"Authorization request received for a token {token_uid} for location {location}."
            )

            if token.language:
                user_language = token.language.lower()

            if not token.valid:
                allowed = AuthorizationEnum.NOT_ALLOWED
                info = MessageTexts.get("TOKEN_NOT_VALID")
                logger.warning(f"Token {token} is marked as invalid in our database.")
                # Todo: Send alert to support?
            else:
                # Todo: Update tests for internal accounting and create tests for MSP authorize callback
                webhook_data = {
                    "token_id": token_uid,
                    "location_id": location.uid if location else None,
                }
                msp_response = send_to_webhook_legacy(
                    webhook_data, MSPAuthorizeCallbackSerializer, timeout=28
                )  # Just under the 30 second limit which is maximum for Heroku requests
                if msp_response:
                    serializer = MSPAuthorizeCallbackSerializer.ResponseSerializer(
                        data=msp_response
                    )
                    if serializer.is_valid():
                        allowed = msp_response.get("result", "NOT_ALLOWED").upper()
                        max_price = msp_response.get("max_price")
                        logger.info(
                            f"MSP backend responded{serializer.data} for {token_uid} at location {location}."
                        )
                    else:
                        allowed = AuthorizationEnum.NOT_ALLOWED
                        logger.error(
                            f"Format error in response from MSP backend: {serializer.errors}"
                        )
                elif token.whitelist in (
                    Token.ALWAYS,
                    Token.ALLOWED,
                    Token.ALLOWED_OFFLINE,
                ):
                    allowed = AuthorizationEnum.ALLOWED
                    info = MessageTexts.get(AuthorizationEnum.ALLOWED)
                else:
                    if (
                        settings.REQUIRE_WALLET_BALANCE
                        and token.total_balance_float() < 1.0
                    ):
                        logger.error(f"Token {token} has no balance")
                        allowed = AuthorizationEnum.NO_CREDIT
                        info = MessageTexts.get("NO_BALANCE")
                    else:
                        allowed = AuthorizationEnum.NOT_ALLOWED
                        info = MessageTexts.get("PROTOCOL_ERROR")

            serializer = TokenSerializer(
                instance=token, context={"version": request.version}
            )

            authorization_reference = (
                generate_auth_reference()
                if allowed == AuthorizationEnum.ALLOWED
                else ""
            )
            if authorization_reference:
                # Todo: Figure out the balance for the token's owner and set the max_price accordingly
                Authorization.objects.create(
                    authorization_reference=authorization_reference, max_price=max_price
                )
                logger.info(
                    f"Created authorization reference {authorization_reference} with max price {max_price}"
                )

            location_dict = (
                {
                    "location_id": location.uid,
                    "evse_uids": [e.uid for e in location.evses.all()],
                }
                if location
                else {}
            )

            return make_ocpi_response(
                TokenAuthorization(
                    allowed=allowed,
                    token=serializer.data,
                    info=info,
                    location=location_dict,
                    authorization_reference=authorization_reference,
                )
            )
        except ValueError as e:
            return OCPIResponse(
                {},
                status_code=Ocpi.ServerError.GENERIC_SERVER_ERROR,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
                status_message=f"{get_language(user_language, info)}: {str(e)}",
            )

    @ocpi_exception_handler
    @requires_credentialsrole
    def get(self, request, credentialsrole, uid=None, **_kwargs):
        """Respond to a GET which has parameters"""

        # Todo: Show only tokens that are relevant to the party
        # Todo: if running as HUB, filter results based on agreed parties
        token = self.get_queryset().get(ocpi_master=credentialsrole, uid=uid)
        serializer = TokenSerializer(
            token, many=False, context={"request": request, "version": request.version}
        )
        return OCPIResponse(serializer.data)

    @staticmethod
    def hub_authorize(request, token, location) -> OCPIResponse:
        """
        Handle a POST request for a token authorization as a hub. Forward the authorization request.
        """
        token_reference = TokenReference(
            uid=token.uid if isinstance(token, Token) else token,
            adhoc=isinstance(token, str),
            token=token if isinstance(token, Token) else None,
        )
        authorization: TokenAuthorization = authorize_token(
            token, location, request=request
        )
        return make_ocpi_response(authorization)


class CdrViewSet(OCPIListModelMixin, GenericViewSet):
    """
    These are the records created for the purpose of billing.
    Once a CDR is created, it must not be modified or removed.
    A CDR can be credited to the customer by creating a credit
    CDR in the admin tools.
    **VISIBILITY**: A CDR record is only available to relevant parties,
    so fetching another party's CDR should not be allowed.
    (When logged in as a superuser, you can see all CDRs)
    """

    # queryset = Cdr.objects.none()  # Default to no visibility, fine tune with get_queryset()
    serializer_class = CdrSerializer
    versioning_class = OCPIVersioning
    pagination_class = OCPIPaginationAndHeaders

    def get_queryset(self):
        if self.request.user.is_superuser:
            return Cdr.objects.all().order_by("created")
        if hasattr(self.request, "country_code"):
            return Cdr.objects.filter(
                ocpi_master=self.request.credentialsrole
            ).order_by("created")
        return Cdr.objects.none()

    def get_view_name(self):
        if hasattr(self, "kwargs") and "uid" in self.kwargs:
            return f'CDR {self.kwargs.get("uid")}'
        if self.name:
            return f"CDR {self.name.lower()}"
        return "Charge Detail Records"

    @staticmethod
    def get_object(uid=None) -> None:
        # Needed for OPTIONS to work in list view
        return None

    @ocpi_exception_handler
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @ocpi_exception_handler
    @requires_sender_role(
        OcpiRolesEnum.EMSP
    )  # CPO should have the specific URL, no need to fetch using this endpoint
    def get(self, request, uid=None, **_kwargs) -> Response:
        cdr = Cdr.objects.get(ocpi_master=request.credentialsrole, uid=uid)
        serializer = CdrSerializer(
            cdr, many=False, context={"request": request, "version": request.version}
        )
        return OCPIResponse(serializer.data)

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.CPO)
    def post(self, request, data, **_kwargs) -> OCPIResponse:
        serializer = CdrSerializer(data=data, context={"version": request.version})
        if serializer.is_valid():
            cdr = serializer.save(ocpi_master=request.credentialsrole)
            # cdr.tariffs.set(tariff_list)
            cdr.send_hub_updates()
            url = build_absolute_uri(cdr.get_absolute_url())
            return OCPIResponse(
                serializer.data,
                headers=dict(Location=url),
                http_status=status.HTTP_201_CREATED,
            )
        return OCPIResponse(errors=serializer.errors)


def make_my_credentials_dict(request, our_token) -> dict:
    return dict(
        token=our_token,
        url=build_absolute_uri(reverse("base-versions")),
        # Todo: Check this, should be "Retrieves the credentials object to access the server’s platform"
        roles=get_our_roles(),
    )


class CredentialsViewSet(mixins.ListModelMixin, GenericViewSet):
    """
    Credential tokens exchange. Please note that the tokens are base64 encoded for transport, except in the
    credentials exchange module. For testing purposes, you can include the token by using
    ?auth-test=TOKEN.
    """

    # The queryset tells Django REST how to determine access to these endpoints
    queryset = Credentials.objects.none()
    serializer_class = CredentialsSerializer

    def get_view_name(self):
        return "Credentials"

    @ocpi_exception_handler
    def list(self, request, *_args, **_kwargs):
        if not hasattr(request, "credentials"):
            return OCPIResponse(
                "There seem to be no credentials in use for this request.",
                http_status=status.HTTP_405_METHOD_NOT_ALLOWED,
                status_code=Ocpi.ClientError.UNKNOWN_TOKEN,
            )
        return OCPIResponse(make_my_credentials_dict(request, request.credentials.ours))

    @ocpi_exception_handler
    def delete(self, request: Request, *_args, **_kwargs):
        # Todo: Make sure deletition is not possible for others than owner
        if not hasattr(request, "credentials"):
            return OCPIResponse(
                "There seem to be no credentials in use for this request.",
                http_status=status.HTTP_405_METHOD_NOT_ALLOWED,
                status_code=Ocpi.ClientError.UNKNOWN_TOKEN,
            )
        logger.warning(
            f"Soft deleting {request.credentials} on request by Credential owner (valid=False)."
        )
        request.credentials.soft_delete()
        return OCPIResponse(
            status_message="Your credentials have been deleted, as requested."
        )

    @ocpi_exception_handler
    @csrf_exempt
    def post(self, request: WSGIRequest, *_args, **_kwargs):
        credentials: Credentials = getattr(request, "credentials", None)
        assert credentials, "Posting to this endpoint requires OCPI Credentials"
        assert not credentials.theirs, "Credentials exist already, use PUT to update"
        data = request.data.get("data", request.data)
        credentials.theirs = data.get("token")
        credentials.url = data.get("url")
        if not credentials.ours:
            credentials.ours = generate_random_token()
        try:
            credentials.roles.all().delete()
            for role in data["roles"]:
                credentials.add_role(role)
        except ProtectedError:
            # If CredentialsRoles are in use, we cannot touch them in any way, so skipping the delete and add_role
            logger.exception("Unable to delete CredentialsRoles")

        # Delay storing tokens until now, in case the roles have some issue
        credentials.save()

        token_base64 = credentials.theirs_base64()  # CREDENTIALS_TOKEN_B
        versions_url = select_version(
            credentials.url, token_base64, credentials_id=credentials.id
        )
        endpoints = get_endpoints(
            versions_url, token_base64, credentials_id=credentials.id
        )
        store_endpoints_for_party(credentials, endpoints)
        data = make_my_credentials_dict(request, our_token=credentials.ours)
        serializer = CredentialsSerializer(
            data=data, context={"version": request.version}
        )
        if not serializer.is_valid():
            logger.error(
                f"Our software has a logic error in Credentials POST: {serializer.errors}"
            )
            return OCPIResponse(
                dict(
                    status_text="Sorry, but we have a slight problem. Support has been alerted."
                ),
                status_code=Ocpi.ServerError.GENERIC_SERVER_ERROR,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        credentials.disable_token_a_if_applicable()
        return OCPIResponse(data, http_status=status.HTTP_201_CREATED)

    @ocpi_exception_handler
    @csrf_exempt
    def put(self, request: Request, *_args, **_kwargs):
        credentials: Credentials = getattr(request, "credentials", None)
        assert credentials, "Posting to this endpoint requires OCPI Credentials"
        assert (
            credentials.theirs and credentials.ours
        ), "Credentials registration has not been finalized, please use POST first"
        data = request.data
        data = data.get("data", data)
        credentials.theirs = data.get("token")
        credentials.url = data.get("url")
        # *Do not allow updating the CredentialsRoles, it is a security vulnerability*
        credentials.save()

        token_base64 = credentials.theirs_base64()  # CREDENTIALS_TOKEN_B
        versions_url = select_version(
            credentials.url, token_base64, credentials_id=credentials.id
        )
        endpoints = get_endpoints(
            versions_url, token_base64, credentials_id=credentials.id
        )
        store_endpoints_for_party(credentials, endpoints)
        data = make_my_credentials_dict(request, our_token=credentials.ours)
        serializer = CredentialsSerializer(
            data=data, context={"version": request.version}
        )
        if not serializer.is_valid():
            logger.error(
                f"Our software has a logic error in Credentials POST: {serializer.errors}"
            )
            return OCPIResponse(
                dict(
                    status_text="Sorry, but we have a slight problem. Support has been alerted."
                ),
                status_code=Ocpi.ServerError.GENERIC_SERVER_ERROR,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        credentials.disable_token_a_if_applicable()
        return OCPIResponse(data)


class TariffViewSet(OCPIListModelMixin, GenericViewSet):
    serializer_class = TariffSerializer
    versioning_class = OCPIVersioning
    pagination_class = OCPIPaginationAndHeaders
    lookup_field = "uid"

    def get_view_name(self):
        if hasattr(self, "kwargs") and "uid" in self.kwargs:
            return f'Tariff {self.kwargs.get("uid")}'
        if self.name:
            return f"{self.name.capitalize()}"
        return "Tariffs"

    def get_queryset(self):
        if ocpi_platform.is_hub and hasattr(self, "request"):
            return (
                Tariff.objects.partner_filter(self.request)
                .exclude(archived=True)
                .order_by("created")
            )
        return Tariff.objects.exclude(archived=True).order_by("created")

    @ocpi_exception_handler
    def list(self, *args, **kwargs):
        return super().list(*args, **kwargs)

    @ocpi_exception_handler
    @requires_credentialsrole
    def get(self, request: Request, credentialsrole, uid, *_args, **_kwargs):
        """Handle a GET request for a specific Tariff"""
        tariff = self.get_queryset().get(ocpi_master=credentialsrole, uid__iexact=uid)
        serializer = self.get_serializer(
            tariff, many=False, context={"request": request, "version": request.version}
        )
        return OCPIResponse(serializer.data)

    @staticmethod
    def get_object(uid=None) -> Tariff:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Tariff, uid=uid)

    @ocpi_exception_handler
    @requires_sender_role([OcpiRolesEnum.CPO, OcpiRolesEnum.HUB])
    @requires_credentialsrole
    def put(
        self,
        request,
        credentialsrole,
        uid=None,
        country_code=None,
        party_id=None,
        data=None,
        version="2.2.1",
    ) -> OCPIResponse:
        assert (
            isinstance(data, dict) and data
        ), f"{self.__class__.__name__}: Data must be dict and have a value, not {data}"
        assert isinstance(credentialsrole, CredentialsRole) and credentialsrole
        uid = uid or data.get("id")

        if request and not request.party_specified_in_url:
            return OCPIUrlParametersRequiredResponse("tariff")

        return self.save_or_update(request, credentialsrole, uid, data, version)

    def save_or_update(
        self, request, credentialsrole, uid, data=None, version="2.2.1"
    ) -> OCPIResponse:
        assert uid, "UID is a required parameter for TariffViewSet.save_or_update()"
        tariff: Tariff = self.get_queryset().get_if_exists(
            uid__iexact=str(uid), ocpi_master=credentialsrole, archived=False
        )
        created = bool(not tariff)
        if tariff and tariff.is_ours():
            return OCPIResponse(
                f"Tariff {tariff} is owned by us and cannot be updated from outside.",
                http_status=status.HTTP_401_UNAUTHORIZED,
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            )
        serializer = TariffSerializer(
            instance=tariff, data=data, context={"version": version, "request": request}
        )
        if serializer.is_valid():
            logger.info(
                f'{"Creating" if created else "Updating"} Tariff {credentialsrole} - {uid}.'
            )
            created_tariff = serializer.save(ocpi_master=credentialsrole)
            created_tariff.send_hub_updates()
            return OCPIResponse(
                serializer.data,
                http_status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            )
        else:
            return OCPIResponse(errors=serializer.errors)

    @ocpi_exception_handler
    @requires_sender_role([OcpiRolesEnum.CPO, OcpiRolesEnum.HUB])
    @requires_credentialsrole
    def delete(self, request, credentialsrole, uid, *_args, **_kwargs) -> OCPIResponse:
        """Process a DELETE rest call for a Tariff"""
        tariff = self.get_queryset().get(uid__iexact=uid, ocpi_master=credentialsrole)
        if (
            tariff.ocpi_master != request.credentialsrole
            and not request.user.is_superuser
            and request.credentials
            and not request.credentials.is_hub
        ):
            return OCPINotOwnerResponse(
                f"Only the owner or a HUB can delete the tariff {uid}."
            )
        if not tariff:
            return OCPIResponse(
                f"No Tariff found with {request.credentialsrole} and uid={uid}.",
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            )
        if (
            hasattr(tariff, "connectors")
            and tariff.connectors
            and tariff.connectors.count()
        ):
            return OCPIResponse(
                "Cannot delete a Tariff which is referred to by one or more Connectors.",
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            )
        tariff.delete()
        return OCPIResponse("Tariff was deleted")


def stop_session_if_money_runs_out(request, session):
    if hasattr(session, "authorization"):
        authorization = session.authorization
        if authorization:
            reserved_money = authorization.max_price
            if (
                reserved_money is not None
                and session.total_cost_incl_vat is not None
                and float(reserved_money) - session.total_cost_incl_vat < 2.0
            ):
                response = send_stop_command(session)
                if response.status_code != status.HTTP_200_OK:
                    logger.error(
                        f"Unable to stop Session {session.uid} before the reserved money {reserved_money} runs out",
                        request,
                    )


def update_authorization(request, session: Session) -> None:
    try:
        if not session.authorization_reference:
            logger.warning(
                f"Session {session.uid} has no authorization_reference, cannot link to Authorization."
            )
            return
        authorization = Authorization.objects.get(
            authorization_reference=session.authorization_reference
        )
        if not authorization.session:
            authorization.session = session
            authorization.save(update_fields=["session"])
            logger.info(
                f"Authorization {session.authorization_reference} is now linked to Session {session.uid}"
            )
    except Authorization.DoesNotExist:
        logger.error(
            f"Authorization {session.authorization_reference} is not known by MSP.",
            request,
        )


class SessionViewSet(OCPIListModelMixin, GenericViewSet):
    pagination_class = OCPIPaginationAndHeaders
    lookup_field = "uid"
    queryset = Session.objects.all().order_by("created")
    serializer_class = SessionSerializer
    versioning_class = OCPIVersioning

    def get_view_name(self):
        if hasattr(self, "kwargs") and "uid" in self.kwargs:
            return f'Session {self.kwargs.get("uid")}'
        if self.name:
            return f"{self.name.capitalize()}"
        return "Sessions"

    @staticmethod
    def get_object(uid=None):
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Session, uid=uid)

    @ocpi_exception_handler
    @requires_credentialsrole
    def get(self, request, credentialsrole, uid, **_kwargs):
        session = Session.objects.get(uid=uid, ocpi_master=credentialsrole)
        cached_session = get_cached_session(session.uid)
        if cached_session and cached_session.kwh > session.stop_kwh:
            session.stop_kwh = cached_session.kwh
        serializer = SessionSerializer(
            session,
            many=False,
            context={"request": request, "version": request.version},
        )
        return OCPIResponse(serializer.data)

    @classmethod
    @ocpi_exception_handler
    @requires_sender_role([OcpiRolesEnum.CPO, OcpiRolesEnum.HUB])
    def put(
        cls,
        request,
        uid,
        *args,
        **kwargs,
    ) -> OCPIResponse:
        country_code = kwargs.get("country_code", "")
        party_id = kwargs.get("party_id", "")
        data = kwargs.get("data", {})
        partial = kwargs.get("partial", False)

        if not request.party_specified_in_url:
            return OCPIUrlParametersRequiredResponse("session")

        session: Session = Session.get_if_exists(
            uid__iexact=uid, ocpi_master=request.credentialsrole
        )
        created = bool(not session)
        if created and partial:
            return OCPIResponse(
                status_message="Unknown Session UID, unable to PATCH.",
                http_status=status.HTTP_404_NOT_FOUND,
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            )

        # Todo: If PATCH fails, we have missed the Session PUT, so we need to fetch the full Session from CPO
        # Todo: Fetch Location if missing
        # Todo: Fetch Tariff if missing
        serializer = SessionSerializer(
            data=request.data,
            instance=session,
            partial=partial,
            context={"request": request, "version": request.version},
        )
        if serializer.is_valid():
            logger.info(
                f'{"Creating" if created else "Updating"} Session {country_code}*{party_id} - {uid}.'
            )
            session = serializer.save(ocpi_master=request.credentialsrole)
            update_authorization(request, session)

            if "last_updated" not in request.data:
                session.update_last_updated()
            session.send_hub_updates()
            # Send the full Session data to MSP webhook, not just the PATCHed fields
            outbound_data = MSPSessionCallbackSerializer.OutboundSerializer(
                instance=session,
                context={
                    "request": request,
                    "ocpi_master": request.credentialsrole,
                    "exclude_urls": True,
                },
            ).data
            send_to_webhook_legacy(
                data, MSPSessionCallbackSerializer, serialized_data=outbound_data
            )
            stop_session_if_money_runs_out(request, session)
            return OCPIResponse(
                serializer.data,
                http_status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            )

        logger.error(
            'Problem with PUT Session from '
            f'{request.credentials if hasattr(request, "credentials") else "?"}: {serializer.errors}'
        )
        return OCPIResponse(
            errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST
        )

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.CPO)
    @requires_last_updated
    def patch(self, request, *args, **kwargs):
        return self.put(request, *args, partial=True, **kwargs)


class ClientInfoViewSet(mixins.ListModelMixin, GenericViewSet):
    """
    The OCPI Hub Client Info endpoint is used for providing
    information on connection status between roaming parties.
    This view shows as empty when accessing it in the Developer Central,
    but when using OCPI credentials, it will show the actual statuses.
    """

    pagination_class = OCPIPaginationAndHeaders
    serializer_class = ClientInfoSerializer

    def get_view_name(self):
        if hasattr(self, "kwargs") and "id" in self.kwargs:
            return f'HubClientInfo {self.kwargs.get("id")}'
        return "HubClientInfo"

    def get_queryset(self):
        return (
            CredentialsRole.objects.partner_filter(self.request)
            .filter(credentials__isnull=False)
            .order_by("country_code", "party_id")
        )

    @staticmethod
    def get_object(object_id=None):
        """Needed for OPTIONS to work in list view, could just return None"""
        if object_id:
            return get_object_or_404(CredentialsRole, pk=object_id)

    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.HUB)
    @requires_credentialsrole  # Are you sure?
    def put(self, request, credentialsrole, *_args, **_kwargs):
        serializer = ClientInfoSerializer(
            data=request.data, context={"request": request, "version": request.version}
        )
        if serializer.is_valid():
            # Todo: Figure out how to create Credentials we don't know about
            return OCPIResponse(serializer.data, http_status=status.HTTP_200_OK)
        return OCPIBadRequestResponse(serializer.errors)


class RootView(routers.APIRootView):
    """
    Welcome to the Developer Central.
    Here you have interactive access to the OCPI 2.2 and 2.2.1 endpoints with examples.

    > **OCPI** is the starting point for the OCPI hierarchy, where the OCPI modules reside.
    >
    > **CPO API** is a cost-effective shortcut to OCPI connectivity.
    >
    > **OpenAPI** provides output which can be imported in popular API browsing tools.
    >
    > **ADMIN UI** link on the top right corner takes you to where you can view and edit the OCPI objects.
    """

    @staticmethod
    def get(request: WSGIRequest, **kwargs):
        result = dict(
            {
                "OCPI 2.2.1": request.build_absolute_uri(
                    reverse("ocpi-221", request=request)
                ),
                # "OpenAPI": request.build_absolute_uri(reverse('openapi-schema', request=request)),
            }
        )
        if ocpi_platform.is_cpo:
            result.update(
                {
                    "CPO API": request.build_absolute_uri(
                        reverse("cpo-api", request=request)
                    )
                }
            )
        if ocpi_platform.is_emsp:
            result.update(
                {
                    "eMSP API": request.build_absolute_uri(
                        reverse("msp-api", request=request)
                    )
                }
            )
        return Response(result)

    def get_view_name(self):
        return "Developer Central"


class RootRouter(routers.DefaultRouter):
    APIRootView = RootView
    root_view_name = "root"


class OcpiApi22View(routers.APIRootView):
    """
    This is the OCPI "endpoints" endpoint. The other party will cache this information to be able to contact
    the available endpoints to update and mirror data structures.
    """

    versioning_class = OCPIVersioning

    @staticmethod
    def get(request, **kwargs):
        return OCPIResponse(get_endpoints_dict(request))

    def get_view_name(self):
        return "Endpoints"


class OCPIRouter(routers.DefaultRouter):
    APIRootView = OcpiApi22View
    root_view_name = "ocpi-22"

    # Make trailing slash optional in URLs
    def __init__(self):
        super().__init__()
        self.trailing_slash = "/?"
