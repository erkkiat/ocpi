"""
EVRF DirectPayment Module API ViewSets

ViewSets for Terminal and FinancialAdviceConfirmation endpoints.
Implements EVRF DirectPayment OCPI 2.2.1 extension specification.

Reference: DirectPayment_2_2_1___EVRF_version.pdf (March 2024)

URL Structure (CPO-side — inbound from PTP):
    GET    /2.2.1/cpo/payments/terminals/              - List terminals
    POST   /2.2.1/cpo/payments/terminals/              - Create terminal (PTP → CPO)
    GET    /2.2.1/cpo/payments/terminals/{terminal_id} - Get terminal
    GET    /2.2.1/cpo/payments/facs/                   - List FACs
    POST   /2.2.1/cpo/payments/facs/                   - Create FAC (PTP → CPO)
    GET    /2.2.1/cpo/payments/facs/{fac_id}           - Get FAC

Note: PATCH and PUT for terminals are PTP-side endpoints (Table 5.1).
SolidRoam calls those outbound on Payter's system to assign locations.
They are NOT inbound endpoints on our CPO side (Table 5.6).

Roles:
    PTP (Payment Terminal Provider like Payter) is SENDER
    CPO (Charge Point Operator) is RECEIVER
"""

from logging import getLogger

from ninja import Router
from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.viewsets import GenericViewSet

from custom_ninja_api import CustomNinjaAPI
from ocpi22.choices import OcpiRolesEnum
from ocpi22.decorators import (
    requires_sender_role,
    requires_credentialsrole,
)
from ocpi22.ocpi.auth import NinjaBasicAuth
from ocpi22.payments.models import Terminal, FinancialAdviceConfirmation
from ocpi22.payments.schemas import TerminalIn, TerminalOut
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
        credentialsrole = getattr(self.request, "credentialsrole", None) or getattr(
            self.request, "ocpi_party", None
        )
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

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.PTP)
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
        credentialsrole = getattr(self.request, "credentialsrole", None) or getattr(
            self.request, "ocpi_party", None
        )
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
    @requires_sender_role(OcpiRolesEnum.PTP)
    @requires_credentialsrole
    def get(self, request, credentialsrole, fac_id: str, **kwargs):
        fac = get_object_or_404(
            FinancialAdviceConfirmation,
            fac_id=fac_id,
            credentials=credentialsrole.credentials,
        )
        return OCPIResponse(FinancialAdviceConfirmationSerializer(fac).data)


class PaymentsRootView(GenericViewSet):
    """
    Stub view for the payments module root URL (/payments/).

    This view exists solely to provide a named URL ("payments-list") that can be
    reversed during the OCPI credentials handshake in get_endpoints_dict(). The
    payments module root has no defined behaviour in the EVRF DirectPayment spec —
    counterparties should use /payments/terminals/ and
    /payments/financial-advice-confirmations/ directly.

    The queryset is required by DjangoModelPermissions which is applied globally.
    """

    queryset = Terminal.objects.none()

    def list(self, request, *args, **kwargs):
        return OCPIResponse(
            http_status=status.HTTP_405_METHOD_NOT_ALLOWED,
            status_code=Ocpi.ClientError.GENERIC_CLIENT_ERROR,
            status_message="Please use /payments/terminals/ or /payments/financial-advice-confirmations/",
        )


payments_ninja_api = CustomNinjaAPI(
    auth=NinjaBasicAuth(),
    urls_namespace="payments",
    title="Payments Ninja API",
)

router = Router()
payments_ninja_api.add_router("/", router)
service = TerminalService()


@router.put("/terminals", response={200: TerminalOut, 404: dict, 422: dict})
def put_terminal(request, payload: TerminalIn):
    terminal = get_object_or_404(Terminal, terminal_id=payload.terminal_id)
    try:
        terminal = service._update_terminal(terminal, payload, partial=False)
    except TerminalValidationError as e:
        return 422, {"message": str(e)}
    service._send_to_ptp(terminal, "put", payload.dict(exclude_unset=False))
    return 200, terminal


@router.patch("/terminals", response={200: TerminalOut, 404: dict, 422: dict})
def patch_terminal(request, payload: TerminalIn):
    terminal = get_object_or_404(Terminal, terminal_id=payload.terminal_id)
    try:
        terminal = service._update_terminal(terminal, payload, partial=True)
    except TerminalValidationError as e:
        return 422, {"message": str(e)}
    service._send_to_ptp(terminal, "patch", payload.dict(exclude_unset=True))
    return 200, terminal
