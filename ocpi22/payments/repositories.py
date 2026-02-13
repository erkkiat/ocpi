from typing import Optional

from django.db.models import QuerySet

from ocpi22.models.credentials import CredentialsRole
from ocpi22.payments.models import Terminal, FinancialAdviceConfirmation


class TerminalRepository:
    @staticmethod
    def get_by_terminal_id_and_credentials(
        terminal_id: str, credentialsrole: CredentialsRole
    ) -> Optional[Terminal]:
        try:
            return Terminal.objects.select_related("credentials").get(
                terminal_id=terminal_id,
                credentials=credentialsrole.credentials,
            )
        except Terminal.DoesNotExist:
            return None

    @staticmethod
    def get_by_terminal_id(terminal_id: str) -> Optional[Terminal]:
        try:
            return Terminal.objects.select_related("credentials").get(
                terminal_id=terminal_id
            )
        except Terminal.DoesNotExist:
            return None

    @staticmethod
    def exists_by_terminal_id_and_credentials(
        terminal_id: str, credentialsrole: CredentialsRole
    ) -> bool:
        return Terminal.objects.filter(
            terminal_id=terminal_id,
            credentials=credentialsrole.credentials,
        ).exists()

    @staticmethod
    def get_all_by_credentials(credentialsrole: CredentialsRole) -> QuerySet[Terminal]:
        return (
            Terminal.objects.filter(credentials=credentialsrole.credentials)
            .select_related("credentials")
            .prefetch_related("locations", "evses")
            .order_by("created")
        )


class FinancialAdviceConfirmationRepository:
    @staticmethod
    def get_by_fac_id_and_credentials(
        fac_id: str, credentialsrole: CredentialsRole
    ) -> Optional[FinancialAdviceConfirmation]:
        try:
            return FinancialAdviceConfirmation.objects.select_related(
                "credentials", "terminal"
            ).get(
                fac_id=fac_id,
                credentials=credentialsrole.credentials,
            )
        except FinancialAdviceConfirmation.DoesNotExist:
            return None

    @staticmethod
    def exists_by_fac_id_and_credentials(
        fac_id: str, credentialsrole: CredentialsRole
    ) -> bool:
        return FinancialAdviceConfirmation.objects.filter(
            fac_id=fac_id,
            credentials=credentialsrole.credentials,
        ).exists()

    @staticmethod
    def get_all_by_credentials(
        credentialsrole: CredentialsRole,
    ) -> QuerySet[FinancialAdviceConfirmation]:
        return (
            FinancialAdviceConfirmation.objects.filter(
                credentials=credentialsrole.credentials
            )
            .select_related("credentials", "terminal")
            .order_by("-created")
        )

    @staticmethod
    def get_by_authorization_reference(
        authorization_reference: str,
    ) -> Optional[FinancialAdviceConfirmation]:
        try:
            return FinancialAdviceConfirmation.objects.select_related(
                "credentials", "terminal"
            ).get(authorization_reference=authorization_reference)
        except FinancialAdviceConfirmation.DoesNotExist:
            return None
