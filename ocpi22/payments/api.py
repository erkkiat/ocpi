"""
EVRF DirectPayment Module API ViewSets

ViewSets for Terminal and FinancialAdviceConfirmation endpoints.
Implements EVRF DirectPayment OCPI 2.2.1 extension specification.

Reference: DirectPayment_2_2_1___EVRF_version.pdf (March 2024)

URL Structure:
    GET    /2.2.1/cpo/payments/terminals - List terminals
    POST   /2.2.1/cpo/payments/terminals - Create terminal (PTP → CPO)
    GET    /2.2.1/cpo/payments/terminals/{terminal_id} - Get terminal
    PUT    /2.2.1/cpo/payments/terminals/{terminal_id} - Update terminal
    PATCH  /2.2.1/cpo/payments/terminals/{terminal_id} - Partial update
    POST   /2.2.1/cpo/payments/facs - Create FAC (PTP → CPO)

Roles:
    PTP (Payment Terminal Provider like Payter) is SENDER
    CPO (Charge Point Operator) is RECEIVER
"""

from logging import getLogger

from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.viewsets import GenericViewSet

from ocpi22.choices import OcpiRolesEnum
from ocpi22.decorators import (
    requires_sender_role,
    requires_credentialsrole,
)
from ocpi22.payments.models import Terminal, FinancialAdviceConfirmation
from ocpi22.payments.serializers import (
    TerminalSerializer,
    FinancialAdviceConfirmationSerializer,
)
from ocpi22.payments.exceptions import (
    TerminalAlreadyExistsError,
    TerminalValidationError,
    FinancialAdviceConfirmationAlreadyExistsError,
    FinancialAdviceConfirmationValidationError,
)
from ocpi22.payments.services import (
    TerminalService,
    FinancialAdviceConfirmationService,
)
from ocpi22.util import OCPIVersioning, OCPIListModelMixin
from ocpi22.ocpi.util import (
    OCPIResponse,
    Ocpi,
    OCPIPaginationAndHeaders,
)
from ocpiconnector.exception_handler import ocpi_exception_handler

logger = getLogger(__name__)


class TerminalViewSet(OCPIListModelMixin, GenericViewSet):
    serializer_class = TerminalSerializer
    pagination_class = OCPIPaginationAndHeaders
    versioning_class = OCPIVersioning
    lookup_field = "terminal_id"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service = TerminalService()

    def get_view_name(self) -> str:
        if hasattr(self, "kwargs") and "terminal_id" in self.kwargs:
            return f'Terminal {self.kwargs.get("terminal_id")}'
        return "Payment Terminals"

    def get_queryset(self):
        credentialsrole = getattr(self.request, "credentialsrole", None)
        if credentialsrole:
            return self.service.get_terminals(credentialsrole)
        return Terminal.objects.none()

    @ocpi_exception_handler
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.PTP)
    @requires_credentialsrole
    def post(self, request, credentialsrole, *args, **kwargs):
        serializer = TerminalSerializer(data=request.data)

        if not serializer.is_valid():
            return OCPIResponse(
                errors=serializer.errors,
                http_status=status.HTTP_400_BAD_REQUEST,
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            )

        try:
            terminal = self.service.create_terminal(
                serializer.validated_data, credentialsrole
            )
            return OCPIResponse(
                TerminalSerializer(terminal).data, http_status=status.HTTP_201_CREATED
            )
        except TerminalAlreadyExistsError as e:
            logger.error(f"Terminal already exists: {e}")
            return OCPIResponse(
                errors=str(e),
                http_status=status.HTTP_400_BAD_REQUEST,
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            )
        except TerminalValidationError as e:
            logger.error(f"Terminal validation failed: {e}")
            return OCPIResponse(
                errors=str(e),
                http_status=status.HTTP_400_BAD_REQUEST,
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            )

    @ocpi_exception_handler
    @requires_credentialsrole
    def get(self, request, credentialsrole, terminal_id: str, **kwargs):
        terminal = get_object_or_404(
            Terminal, terminal_id=terminal_id, credentials=credentialsrole.credentials
        )
        return OCPIResponse(TerminalSerializer(terminal).data)


class FinancialAdviceConfirmationViewSet(OCPIListModelMixin, GenericViewSet):
    serializer_class = FinancialAdviceConfirmationSerializer
    pagination_class = OCPIPaginationAndHeaders
    versioning_class = OCPIVersioning
    lookup_field = "fac_id"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service = FinancialAdviceConfirmationService()

    def get_view_name(self) -> str:
        return "Financial Advice Confirmations"

    def get_queryset(self):
        credentialsrole = getattr(self.request, "credentialsrole", None)
        if credentialsrole:
            return self.service.get_facs(credentialsrole)
        return FinancialAdviceConfirmation.objects.none()

    @ocpi_exception_handler
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.PTP)
    @requires_credentialsrole
    def post(self, request, credentialsrole, *args, **kwargs):
        serializer = FinancialAdviceConfirmationSerializer(data=request.data)

        if not serializer.is_valid():
            return OCPIResponse(
                errors=serializer.errors,
                http_status=status.HTTP_400_BAD_REQUEST,
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            )

        terminal_id = request.data.get("terminal_id")

        try:
            fac = self.service.create_fac(
                serializer.validated_data, credentialsrole, terminal_id=terminal_id
            )
            return OCPIResponse(
                FinancialAdviceConfirmationSerializer(fac).data,
                http_status=status.HTTP_201_CREATED,
            )
        except FinancialAdviceConfirmationAlreadyExistsError as e:
            logger.error(f"FAC already exists: {e}")
            return OCPIResponse(
                errors=str(e),
                http_status=status.HTTP_400_BAD_REQUEST,
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            )
        except FinancialAdviceConfirmationValidationError as e:
            logger.error(f"FAC validation failed: {e}")
            return OCPIResponse(
                errors=str(e),
                http_status=status.HTTP_400_BAD_REQUEST,
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            )

    @ocpi_exception_handler
    @requires_credentialsrole
    def get(self, request, credentialsrole, fac_id: str, **kwargs):
        fac = get_object_or_404(
            FinancialAdviceConfirmation,
            fac_id=fac_id,
            credentials=credentialsrole.credentials,
        )
        return OCPIResponse(FinancialAdviceConfirmationSerializer(fac).data)
