import logging

from rest_framework import status
from rest_framework.viewsets import GenericViewSet

from ocpi22.commands.serializers import (
    StartSessionSerializer,
    StopSessionSerializer,
)
from ocpi22.commands.services import (
    InvalidSenderPartyError,
    RemoteCommandServices,
    StartCommandService,
    StopCommandServices,
)
from ocpi22.decorators import requires_sender_role
from ocpi22.choices import OcpiRolesEnum
from ocpi22.models.session import Session
from ocpi22.ocpi.auth import OCPIPermission
from ocpi22.ocpi.util import OCPIResponse, options_message, OCPIBadRequestResponse
from ocpi22.util import OCPIVersioning
from ocpiconnector.exception_handler import ocpi_exception_handler
from webhooks.choices import RemoteCommandType

logger = logging.getLogger(__name__)


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
        start_command_service = StartCommandService()

        try:
            sender_party = start_command_service.get_validated_sender_party(
                request.META
            )
        except InvalidSenderPartyError as e:
            logger.exception(e)
            return OCPIBadRequestResponse(status_message=e.args[0])

        try:
            ocpi_response = start_command_service.start_session(
                sender_party=sender_party,
                credentials=request.credentials,
                validated_data=serializer.validated_data,
            )
            return ocpi_response
        except Exception:
            logger.error("Could not process remote start command", exc_info=True)
            return RemoteCommandServices().create_ocpi_response(
                {}, RemoteCommandType.START_SESSION
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
            return RemoteCommandServices().create_ocpi_response(
                {}, RemoteCommandType.STOP_SESSION
            )

        try:
            stop_command_service = StopCommandServices()
            response = stop_command_service.stop_session(validated_data=serializer.data)
            return response
        except Exception:
            logger.error("Could not process remote stop command", exc_info=True)
            return RemoteCommandServices().create_ocpi_response({}, "STOP")
