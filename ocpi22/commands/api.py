from rest_framework import status
from rest_framework.viewsets import GenericViewSet

from ocpi22.commands.serializers import (
    StartSessionSerializer,
    StopSessionSerializer,
    ReserveNowSerializer,
)
from ocpi22.commands.services import (
    StartSessionService,
    StopSessionService,
    ReserveNowService,
    get_validated_sender_party,
    InvalidSenderPartyError,
)
from ocpi22.decorators import requires_sender_role
from ocpi22.choices import OcpiRolesEnum
from ocpi22.models.session import Session
from ocpi22.ocpi.auth import OCPIPermission
from ocpi22.ocpi.util import OCPIResponse, options_message, OCPIBadRequestResponse
from ocpi22.util import OCPIVersioning
from ocpiconnector.exception_handler import ocpi_exception_handler


class CommandsViewSet(GenericViewSet):
    queryset = (
        Session.objects.none()
    )  # Users who can access Sessions can issue Commands also
    versioning_class = OCPIVersioning
    permission_classes = [OCPIPermission]

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.EMSP)
    def start_session(self, request, **kwargs):
        if not request.data:
            return OCPIResponse(
                {"status_message": options_message}, status=status.HTTP_400_BAD_REQUEST
            )

        serializer = StartSessionSerializer(
            data=request.data, context={"request": request}
        )
        if not serializer.is_valid():
            return OCPIResponse(
                serializer.errors,
                status_message="Please check your request parameters",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            sender_party = get_validated_sender_party(request.META)
        except InvalidSenderPartyError as e:
            return OCPIBadRequestResponse(status_message=e.args[0])

        service = StartSessionService()
        return service.start_session(
            sender_party=sender_party,
            ocpi_party=request.ocpi_party,
            credentials=request.credentials,
            validated_data=serializer.validated_data,
        )

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.EMSP)
    def stop_session(self, request, **kwargs):
        if not request.data:
            return OCPIResponse(
                {"status_message": options_message}, status=status.HTTP_400_BAD_REQUEST
            )

        serializer = StopSessionSerializer(
            data=request.data, context={"request": request}
        )
        if not serializer.is_valid():
            return OCPIResponse(
                serializer.errors,
                status_message="Please check your request parameters",
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        sender_party = get_validated_sender_party(request.META)
        service = StopSessionService()
        return service.stop_session(
            sender_party=sender_party,
            ocpi_party=request.ocpi_party,
            credentials=request.credentials,
            validated_data=serializer.validated_data,
        )

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.EMSP)
    def reserve_now(self, request, **kwargs):
        if not request.data:
            return OCPIResponse(
                {"status_message": options_message}, status=status.HTTP_400_BAD_REQUEST
            )

        serializer = ReserveNowSerializer(
            data=request.data, context={"request": request}
        )
        if not serializer.is_valid():
            return OCPIResponse(
                serializer.errors,
                status_message="Please check your request parameters",
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        sender_party = get_validated_sender_party(request.META)
        service = ReserveNowService()
        return service.reserve_now(
            sender_party=sender_party,
            ocpi_party=request.ocpi_party,
            credentials=request.credentials,
            validated_data=serializer.validated_data,
        )
