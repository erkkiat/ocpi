from logging import getLogger
from typing import Optional

from django.db import transaction

from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.location import Location, Evse
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

    def _assign_locations_and_evses(
        self, terminal: Terminal, location_ids: list, evse_uids: list
    ) -> None:
        if location_ids:
            locations = Location.objects.filter(uid__in=location_ids)
            terminal.locations.set(locations)

        if evse_uids:
            evses = Evse.objects.filter(uid__in=evse_uids)
            terminal.evses.set(evses)

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

        location_ids = validated_data.pop("location_ids", [])
        evse_uids = validated_data.pop("evse_uids", [])

        terminal = Terminal(**validated_data)
        terminal.credentials = credentialsrole.credentials
        terminal.save()

        self._assign_locations_and_evses(terminal, location_ids, evse_uids)

        return terminal

    @transaction.atomic
    def update_terminal(
        self,
        terminal_id: str,
        validated_data: dict,
        credentialsrole: CredentialsRole,
        partial: bool = False,
    ) -> tuple[Terminal, bool]:
        terminal = self.get_terminal_by_id(terminal_id, credentialsrole)

        location_ids = validated_data.pop("location_ids", None)
        evse_uids = validated_data.pop("evse_uids", None)

        if terminal:
            logger.info(
                f"Updating terminal {terminal_id} for {credentialsrole.get_party()}"
            )

            for field, value in validated_data.items():
                setattr(terminal, field, value)

            terminal.save()

            if location_ids is not None:
                self._assign_locations_and_evses(
                    terminal, location_ids, evse_uids or []
                )
            elif evse_uids is not None:
                self._assign_locations_and_evses(terminal, [], evse_uids)

            return terminal, False
        else:
            logger.info(
                f"Terminal {terminal_id} not found, creating new terminal for {credentialsrole.get_party()}"
            )
            validated_data["terminal_id"] = terminal_id
            validated_data["location_ids"] = location_ids or []
            validated_data["evse_uids"] = evse_uids or []

            new_terminal = self.create_terminal(validated_data, credentialsrole)
            return new_terminal, True


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

    def _get_terminal_for_fac(
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
            terminal = self._get_terminal_for_fac(terminal_id, credentialsrole)
            if not terminal:
                raise FinancialAdviceConfirmationValidationError(
                    f"Terminal with ID {terminal_id} not found for this party"
                )
            fac.terminal = terminal

        fac.save()
        return fac
