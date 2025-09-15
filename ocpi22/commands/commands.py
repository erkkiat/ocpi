from builtins import list
from typing import Union, Optional

from logging import getLogger
from django.views.decorators.csrf import csrf_exempt

from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urljoin

from django.conf import settings
from django.utils.datetime_safe import datetime
from rest_framework import serializers, status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response

from ocpi22.decorators import requires_sender_role
from ocpi22.msp.models import Authorization
from ocpi22.tasks import send_ocpi_request
from ocpiconnector.exception_handler import ocpi_exception_handler
from util import reverse
from rest_framework.viewsets import GenericViewSet

from ocpi22.util import OCPIVersioning
from ocpi22.ocpi.serializers import TokenSerializer
from ocpi22.ocpi.auth import OCPIPermission
from ocpi22.choices import OcpiModuleEnum, OcpiRolesEnum
from ocpi22.commands.serializers import (
    StartSessionSerializer,
    StopSessionSerializer,
    UnlockConnectorSerializer,
    CommandResponse,
    CommandResultSerializer,
    ReserveNowSerializer,
)
from ocpi22.models.location import Evse, Location
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.routing import find_route, Route
from ocpi22.ocpi.util import (
    ocpi_post,
    OCPIResponse,
    Ocpi,
    generate_auth_reference,
    options_message,
)

from ocpi22.tokens.util import construct_adhoc_token
from ocpiconnector.ocpi_identities import get_our_party, ocpi_platform
from ocpiconnector.party import Party
from ocpi22.util import build_absolute_uri, command_store

logger = getLogger(__name__)


@dataclass(eq=True)
class ResponseData:
    ocpi_status: int
    result: str
    http_status: int
    message: list
    timeout: int


class CommandsViewSetLegacy(GenericViewSet):
    # root_view_name = 'commands'
    queryset = (
        Session.objects.none()
    )  # Users who can access Sessions can issue Commands also
    versioning_class = OCPIVersioning
    permission_classes = [OCPIPermission]

    def get_serializer_class(self):
        if not hasattr(self, "action_map"):
            return serializers.Serializer
        serializer = dict(
            start_session=StartSessionSerializer,
            stop_session=StopSessionSerializer,
            unlock_connector=UnlockConnectorSerializer,
            reserve_now=ReserveNowSerializer,
            command_result=CommandResultSerializer,
        ).get(self.action_map.get("post"), serializers.Serializer)
        return serializer

    def get_view_name(self):
        if hasattr(self, "kwargs") and "uid" in self.kwargs:
            return f"Command {self.kwargs.get('uid')}"
        if self.name:
            return f"{self.name.capitalize()}"
        return "Commands"

    error_response = ResponseData(
        ocpi_status=2000,
        result=CommandResponse.REJECTED,
        http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        message=[],
        timeout=60,
    )

    # These methods have been moved to the service classes
    # Keeping them for reference but they're not used anymore

    # @ocpi_exception_handler
    # @requires_sender_role(OcpiRolesEnum.EMSP)
    # def reserve_now(self, request, **_kwargs):
    #     if not request.data:
    #         return OCPIResponse(
    #             {"status_message": options_message}, status=status.HTTP_400_BAD_REQUEST
    #         )
    #
    #     serializer = ReserveNowSerializer(
    #         data=request.data, context={"request": request, "version": request.version}
    #     )
    #     if not serializer.is_valid():
    #         return OCPIResponse(
    #             serializer.errors,
    #             status_message="Please check your request parameters",
    #             http_status=status.HTTP_400_BAD_REQUEST,
    #             status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
    #         )
    #
    #     service = ReserveNowService()
    #     return service.reserve_now(request, serializer.validated_data)

    @ocpi_exception_handler
    @csrf_exempt
    def hubresponse(self, request, command_id, version="2.2.1"):
        if not ocpi_platform.is_hub:
            return OCPIResponse(
                status_code=Ocpi.ServerError.GENERIC_SERVER_ERROR,
                http_status=status.HTTP_404_NOT_FOUND,
            )
        command_data = command_store[command_id]
        if command_data:
            route_dict = command_data.get("route_back")
            print(f"{route_dict=}")
            route: Route = Route(**route_dict)
            our_hub_party: Party = get_our_party(OcpiRolesEnum.HUB)

            if route:
                response = send_ocpi_request(  # Todo: How about just data, route as parameters?
                    request.data,
                    url=route.url,
                    token_base64=route.token_base64,
                    to_country_code=route.to.get("country_code"),
                    to_party_id=route.to.get("party_id"),
                    from_country_code=our_hub_party.country_code,
                    from_party_id=our_hub_party.party_id,
                    method="post",
                    credentials_id=route.credentials_id,
                    title="the response received from CPO",
                )
                status_code = {
                    200: Ocpi.OK,
                }.get(
                    response.get("status_code", 400),
                    Ocpi.ServerError.GENERIC_SERVER_ERROR,
                )
                return OCPIResponse(
                    status_code=status_code, http_status=response.get("status_code")
                )
        return OCPIResponse(
            status_code=Ocpi.ServerError.GENERIC_SERVER_ERROR,
            http_status=status.HTTP_404_NOT_FOUND,
        )

    # Exception handling is done in the calling method, no need for it here

    # @ocpi_exception_handler
    # @requires_sender_role(OcpiRolesEnum.EMSP)
    # def stop_session(self, request, **_kwargs):
    #     if not request.data:
    #         return OCPIResponse(
    #             {"status_message": options_message}, status=status.HTTP_400_BAD_REQUEST
    #         )
    #
    #     serializer = StopSessionSerializer(
    #         data=request.data, context={"request": request, "version": request.version}
    #     )
    #     if not serializer.is_valid():
    #         return OCPIResponse(
    #             serializer.errors,
    #             status_message="Please check your request parameters",
    #             http_status=status.HTTP_400_BAD_REQUEST,
    #             status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
    #         )
    #
    #     service = StopSessionService()
    #     return service.stop_session(request, serializer.validated_data)

    # This method has been moved to StopSessionService
    # Keeping for reference but not used anymore

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.EMSP)
    def unlock_connector(self, request, **_kwargs):
        if not request.data:
            return OCPIResponse(
                {"status_message": options_message}, status=status.HTTP_400_BAD_REQUEST
            )
        serializer = UnlockConnectorSerializer(data=request.data)
        if serializer.is_valid():
            result = "ACCEPTED"

            response_serializer = CommandResponse(
                instance=dict(
                    result=result,
                    timeout=120,
                    message=[
                        dict(language="EN", text="Unlocking connector"),
                        dict(language="FI", text="Liittimen lukitus vapautetaan"),
                    ],
                )
            )
            return OCPIResponse(response_serializer.data)
        else:
            return OCPIResponse(
                serializer.errors,
                status_message="Please check your request parameters",
                http_status=status.HTTP_400_BAD_REQUEST,
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            )

    @ocpi_exception_handler
    def command_result(self, request, command=None, command_id=None, version="2.2.1"):
        """
        This is only used by eMSP for receiving the final result for remote command
        """
        if not request.data:
            return OCPIResponse(
                {"status_message": options_message}, status=status.HTTP_400_BAD_REQUEST
            )
        session = Session.objects.filter(authorization_reference=command_id)
        authorization = Authorization.objects.filter(authorization_reference=command_id)
        if not session.exists() and not authorization:
            return OCPIResponse(
                "Session not found",
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        if session.count() > 1:
            logger.error(
                f"Multiple Sessions found with the same authorization reference {command_id}"
            )

        serializer = CommandResultSerializer(data=request.data)
        if serializer.is_valid():
            result = serializer.validated_data.get("result")
            message = serializer.validated_data.get("message")
            session.update(message=message)
            logger.info(
                f"Received CommandResult {result} and "
                f"message {message or 'N/A'} for command {command} ID {command_id}"
            )
            # Todo: Embed any error or success text to the Session status response
            return OCPIResponse(
                status_message="Command result received, thank you!",
                data=dict(command_id=command_id),
            )
        return OCPIResponse(
            serializer.errors,
            status_message="Please check your request parameters",
            http_status=status.HTTP_400_BAD_REQUEST,
            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
        )

    @staticmethod
    @ocpi_exception_handler
    def list(request, *_args, **_kwargs):
        return Response(
            dict(
                start_session=request.build_absolute_uri(
                    reverse("commands-start-session", request=request)
                ),
                stop_session=request.build_absolute_uri(
                    reverse("commands-stop-session", request=request)
                ),
                unlock_connector=request.build_absolute_uri(
                    reverse("commands-unlock-connector", request=request)
                ),
                reserve_now=request.build_absolute_uri(
                    reverse("commands-reserve-now", request=request)
                ),
                # command_result=request.build_absolute_uri(reverse('commands-command-result')),
            )
        )


def send_start_command(
    request,
    evse: Evse,
    token: Union[Token, str],
    connector_id=None,
    contract_id="",
    authorization_reference: str = None,
) -> Response:
    """
    As an eMSP we send an OCPI Command START_SESSION to the CPO
    """
    country_code = evse.location.ocpi_master.country_code
    party_id = evse.location.ocpi_master.party_id

    route: Route = find_route(Party(country_code, party_id), OcpiModuleEnum.COMMANDS)
    if route:
        logger.info(
            f"*** Sending start command for {evse.location.name} to {route.url}."
        )
        if not isinstance(token, Token):
            token = construct_adhoc_token(token, contract_id=contract_id)
        token_data = TokenSerializer(token).data
        data = dict(
            response_url=build_absolute_uri(
                reverse(
                    "commands-command-result",
                    args=(
                        "start",
                        authorization_reference,
                    ),
                )
            ),
            token=token_data,
            location_id=evse.location.uid,
            evse_uid=evse.uid,
            connector_id=connector_id,
            authorization_reference=authorization_reference,
        )
        if route.version == "2.2":
            data.pop("connector_id", None)
        serializer = StartSessionSerializer(data=data)
        if not serializer.is_valid():
            logger.error("Malformed outbound data in send_start_command() (system bug)")
            logger.error(serializer.errors)
            raise ValidationError("Malformed outbound data (system bug)")
        return ocpi_post(
            urljoin(f"{route.url}/", "START_SESSION"),
            route.token_base64,
            to=Party(country_code, party_id),
            sender=get_our_party(OcpiRolesEnum.EMSP),
            data=serializer.data,
        )
    else:
        message = (
            f"Cannot find a route for START_SESSION to {evse.location.party_str()}"
        )
        logger.error(message)
        raise APIException(message)


def send_reserve_command(
    request,
    location: Location,
    evse: Evse,
    token: Union[Token, str],
    reservation_id,
    connector_id=None,
    contract_id="",
    expiration=settings.MAXIMUM_RESERVATION,
) -> Response:
    """
    As an eMSP we send an OCPI Command RESERVE_NOW to the CPO
    """
    country_code = evse.location.ocpi_master.country_code
    party_id = evse.location.ocpi_master.party_id

    route: Route = find_route(Party(country_code, party_id), OcpiModuleEnum.COMMANDS)
    if route:
        logger.info(
            f"*** Sending reserve command for {evse.location.name} to {route.url}."
        )
        if not isinstance(token, Token):
            token = construct_adhoc_token(token, contract_id=contract_id)
        token_data = TokenSerializer(token).data
        authorization_reference = generate_auth_reference()
        if evse.location != location:
            raise Evse.DoesNotExist(
                f"The EVSE {evse.evse_id} is not at location {location.uid}"
            )
        data = dict(
            response_url=build_absolute_uri(
                reverse(
                    "commands-command-result",
                    args=(
                        "reserve",
                        authorization_reference,
                    ),
                )
            ),
            token=token_data,
            location_id=location.uid,
            evse_uid=evse.uid,
            connector_id=connector_id,
            authorization_reference=authorization_reference,
            expiry_date=datetime.now() + timedelta(seconds=expiration),
            reservation_id=reservation_id,
        )
        serializer = ReserveNowSerializer(data=data)
        if not serializer.is_valid():
            logger.error(
                "Malformed outbound data in send_reserve_command() (system bug)"
            )
            logger.error(serializer.errors)
            raise ValidationError("Malformed outbound data (system bug)")
        return ocpi_post(
            urljoin(f"{route.url}/", "RESERVE_NOW"),
            route.token_base64,
            to=Party(country_code, party_id),
            sender=get_our_party(OcpiRolesEnum.EMSP),
            data=serializer.data,
        )
    else:
        message = f"Cannot find a route for RESERVE_NOW to {evse.location.party_str()}"
        logger.error(message)
        raise APIException(message)


def send_stop_command(session: Session) -> Optional[Response]:
    country_code = session.location.ocpi_master.country_code
    party_id = session.location.ocpi_master.party_id

    route: Route = find_route(Party(country_code, party_id), OcpiModuleEnum.COMMANDS)
    if route:
        logger.info(f"*** Sending stop command for {session} to {route.url}.")
        authorization_reference = session.authorization_reference
        data = dict(
            response_url=build_absolute_uri(
                reverse(
                    "commands-command-result",
                    args=(
                        "stop",
                        authorization_reference,
                    ),
                )
            ),
            session_id=session.uid,
        )
        serializer = StopSessionSerializer(instance=data)
        return ocpi_post(
            urljoin(f"{route.url}/", "STOP_SESSION"),
            route.token_base64,
            to=Party(country_code, party_id),
            sender=get_our_party(OcpiRolesEnum.EMSP),
            data=serializer.data,
        )
    else:
        message = f"Cannot find a route for STOP_SESSION to {country_code}*{party_id}"
        logger.error(message)
        raise APIException(message)
