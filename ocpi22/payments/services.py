from logging import getLogger
from typing import Optional

from django.db import transaction
from django.db.models import QuerySet

from ocpi22.models.credentials import CredentialsRole
from ocpi22.payments.exceptions import (
    TerminalAlreadyExistsError,
    FinancialAdviceConfirmationAlreadyExistsError,
    FinancialAdviceConfirmationValidationError,
)
from ocpi22.payments.models import Terminal, FinancialAdviceConfirmation
from ocpi22.payments.repositories import (
    TerminalRepository,
    FinancialAdviceConfirmationRepository,
)

logger = getLogger(__name__)


class TerminalService:
    def __init__(self, repository: TerminalRepository = None):
        self.repository = repository or TerminalRepository()

    def get_terminal_by_id(
        self, terminal_id: str, credentialsrole: CredentialsRole
    ) -> Optional[Terminal]:
        return self.repository.get_by_terminal_id_and_credentials(
            terminal_id, credentialsrole
        )

    def get_terminals(self, credentialsrole: CredentialsRole) -> QuerySet[Terminal]:
        return self.repository.get_all_by_credentials(credentialsrole)

    @transaction.atomic
    def create_terminal(
        self, validated_data: dict, credentialsrole: CredentialsRole
    ) -> Terminal:
        terminal_id = validated_data["terminal_id"]

        if self.repository.exists_by_terminal_id(terminal_id):
            raise TerminalAlreadyExistsError(
                f"Terminal with ID {terminal_id} already exists"
            )

        logger.info(
            f"Creating terminal {terminal_id} for {credentialsrole.get_party()}"
        )

        terminal = Terminal(**validated_data)
        terminal.credentials = credentialsrole.credentials
        terminal.save()

        return terminal


class FinancialAdviceConfirmationService:
    def __init__(
        self,
        fac_repository: FinancialAdviceConfirmationRepository = None,
        terminal_repository: TerminalRepository = None,
    ):
        self.fac_repository = fac_repository or FinancialAdviceConfirmationRepository()
        self.terminal_repository = terminal_repository or TerminalRepository()

    def get_fac_by_id(
        self, fac_id: str, credentialsrole: CredentialsRole
    ) -> Optional[FinancialAdviceConfirmation]:
        return self.fac_repository.get_by_fac_id_and_credentials(
            fac_id, credentialsrole
        )

    def get_facs(
        self, credentialsrole: CredentialsRole
    ) -> QuerySet[FinancialAdviceConfirmation]:
        return self.fac_repository.get_all_by_credentials(credentialsrole)

    def _get_terminal_or_raise(
        self, terminal_id: str, credentialsrole: CredentialsRole
    ) -> Terminal:
        terminal = self.terminal_repository.get_by_terminal_id_and_credentials(
            terminal_id, credentialsrole
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
        fac_id = validated_data["fac_id"]

        if self.fac_repository.exists_by_fac_id_and_credentials(
            fac_id, credentialsrole
        ):
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
            fac.terminal = self._get_terminal_or_raise(terminal_id, credentialsrole)

        fac.save()
        return fac
