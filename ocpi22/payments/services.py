from logging import getLogger
from typing import Optional

from django.db import transaction

from ocpi22.models.credentials import CredentialsRole
from ocpi22.payments.models import Terminal, FinancialAdviceConfirmation
from ocpi22.payments.exceptions import (
    TerminalAlreadyExistsError,
    TerminalValidationError,
    FinancialAdviceConfirmationAlreadyExistsError,
    FinancialAdviceConfirmationValidationError,
)

logger = getLogger(__name__)


class TerminalService:
    def get_terminal_by_id(
        self, terminal_id: str, credentialsrole: CredentialsRole
    ) -> Optional[Terminal]:
        return (
            Terminal.objects.filter(
                terminal_id=terminal_id,
                credentials=credentialsrole.credentials,
            )
            .select_related("credentials")
            .first()
        )

    def get_terminals(self, credentialsrole: CredentialsRole):
        return (
            Terminal.objects.filter(credentials=credentialsrole.credentials)
            .select_related("credentials")
            .prefetch_related("locations", "evses")
            .order_by("created")
        )

    def _validate_terminal_identification(self, data: dict) -> None:
        customer_ref = bool(data.get("customer_reference"))
        party_info = bool(data.get("party_id") and data.get("country_code"))

        if not customer_ref and not party_info:
            raise TerminalValidationError(
                "Either customer_reference or (party_id + country_code) must be provided"
            )

    def _check_terminal_exists(
        self, terminal_id: str, credentialsrole: CredentialsRole
    ) -> bool:
        return Terminal.objects.filter(
            terminal_id=terminal_id,
            credentials=credentialsrole.credentials,
        ).exists()

    @transaction.atomic
    def create_terminal(
        self, validated_data: dict, credentialsrole: CredentialsRole
    ) -> Terminal:
        terminal_id = validated_data.get("terminal_id")

        if self._check_terminal_exists(terminal_id, credentialsrole):
            raise TerminalAlreadyExistsError(
                f"Terminal with ID {terminal_id} already exists for this party"
            )

        self._validate_terminal_identification(validated_data)

        logger.info(
            f"Creating terminal {terminal_id} for {credentialsrole.get_party()}"
        )

        terminal = Terminal(**validated_data)
        terminal.credentials = credentialsrole.credentials
        terminal.save()

        return terminal


class FinancialAdviceConfirmationService:
    def get_fac_by_id(
        self, fac_id: str, credentialsrole: CredentialsRole
    ) -> Optional[FinancialAdviceConfirmation]:
        return (
            FinancialAdviceConfirmation.objects.filter(
                fac_id=fac_id,
                credentials=credentialsrole.credentials,
            )
            .select_related("credentials", "terminal")
            .first()
        )

    def get_facs(self, credentialsrole: CredentialsRole):
        return (
            FinancialAdviceConfirmation.objects.filter(
                credentials=credentialsrole.credentials
            )
            .select_related("credentials", "terminal")
            .order_by("-created")
        )

    def _check_fac_exists(self, fac_id: str, credentialsrole: CredentialsRole) -> bool:
        return FinancialAdviceConfirmation.objects.filter(
            fac_id=fac_id,
            credentials=credentialsrole.credentials,
        ).exists()

    def _validate_terminal_exists(
        self, terminal_id: str, credentialsrole: CredentialsRole
    ) -> Terminal:
        terminal = (
            Terminal.objects.filter(
                terminal_id=terminal_id,
                credentials=credentialsrole.credentials,
            )
            .select_related("credentials")
            .first()
        )

        if not terminal:
            raise FinancialAdviceConfirmationValidationError(
                f"Terminal with ID {terminal_id} not found for this party"
            )

        return terminal

    @transaction.atomic
    def create_fac(
        self,
        validated_data: dict,
        credentialsrole: CredentialsRole,
        terminal_id: Optional[str] = None,
    ) -> FinancialAdviceConfirmation:
        fac_id = validated_data.get("fac_id")

        if self._check_fac_exists(fac_id, credentialsrole):
            raise FinancialAdviceConfirmationAlreadyExistsError(
                f"FAC with ID {fac_id} already exists for this party"
            )

        logger.info(
            f"Creating FAC {fac_id} for authorization_reference "
            f"{validated_data.get('authorization_reference')} by {credentialsrole.get_party()}"
        )

        fac = FinancialAdviceConfirmation(**validated_data)
        fac.credentials = credentialsrole.credentials

        if terminal_id:
            terminal = self._validate_terminal_exists(terminal_id, credentialsrole)
            fac.terminal = terminal

        fac.save()
        return fac
