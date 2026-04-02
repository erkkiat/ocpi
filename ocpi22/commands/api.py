import logging

from rest_framework import status
from rest_framework.viewsets import GenericViewSet

from ocpi22.commands.serializers import (
    StartSessionSerializer,
    StopSessionSerializer,
    CommandResponseType,
)
from ocpi22.commands.services import (
    RemoteCommandServices,
    StartCommandService,
    StopCommandServices,
)
from ocpi22.decorators import requires_sender_role
from ocpi22.choices import OcpiRolesEnum
from ocpi22.exceptions import (
    EvseOccupiedError,
    EvseNotFoundError,
    LocationNotFoundError,
    ConnectorNotFoundError,
)
from ocpi22.models.session import Session
from ocpi22.ocpi.auth import OCPIPermission
from ocpi22.ocpi.util import OCPIResponse, options_message
from ocpi22.util import OCPIVersioning
from ocpiconnector.exception_handler import ocpi_exception_handler

logger = logging.getLogger(__name__)


class CommandsViewSet(GenericViewSet):
    queryset = (
        Session.objects.none()
    )  # Users who can access Sessions can issue Commands also
    versioning_class = OCPIVersioning
    permission_classes = [OCPIPermission]

    @ocpi_exception_handler
    @requires_sender_role([OcpiRolesEnum.EMSP, OcpiRolesEnum.PTP])
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
            ocpi_response = start_command_service.start_session(
                billed_to=request.credentialsrole,
                credentials=request.credentials,
                validated_data=serializer.validated_data,
            )
            return ocpi_response
        except (
            EvseOccupiedError,
            EvseNotFoundError,
            LocationNotFoundError,
            ConnectorNotFoundError,
        ) as e:
            logger.exception(e)
            return start_command_service.create_ocpi_response(
                CommandResponseType.REJECTED, e.args[0]
            )
        except Exception as e:
            logger.exception(e)
            return start_command_service.create_ocpi_response(
                CommandResponseType.REJECTED
            )

    @ocpi_exception_handler
    @requires_sender_role([OcpiRolesEnum.EMSP, OcpiRolesEnum.PTP])
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
                CommandResponseType.REJECTED
            )

        try:
            stop_command_service = StopCommandServices()
            response = stop_command_service.stop_session(validated_data=serializer.data)
            return response
        except Exception:
            logger.error("Could not process remote stop command", exc_info=True)
            return RemoteCommandServices().create_ocpi_response(
                CommandResponseType.REJECTED
            )
