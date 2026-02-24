from logging import getLogger
from typing import Optional

from django.db import transaction
from django.db.models import QuerySet

from ocpi22.choices import OcpiRolesEnum
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.location import Location, Evse
from ocpi22.payments.exceptions import (
    TerminalAlreadyExistsError,
    FinancialAdviceConfirmationAlreadyExistsError,
    FinancialAdviceConfirmationValidationError, TerminalValidationError,
)
from ocpi22.payments.models import Terminal, FinancialAdviceConfirmation
from ocpi22.payments.repositories import (
    TerminalRepository,
    FinancialAdviceConfirmationRepository,
)
from ocpi22.payments.schemas import TerminalIn
from ocpi22.tasks import send_ocpi_request
from ocpiconnector.ocpi_identities import get_our_party
from util import with_trailing_slash

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

    def _update_terminal(self, terminal: Terminal, payload: TerminalIn, partial: bool = False) -> Terminal:
        payload_dict = payload.dict(exclude_unset=partial)

        if "customer_reference" in payload_dict:
            terminal.customer_reference = payload_dict["customer_reference"]
        if "invoice_base_url" in payload_dict:
            terminal.invoice_base_url = payload_dict["invoice_base_url"]
        if "last_updated" in payload_dict:
            terminal.last_updated = payload_dict["last_updated"]

        if "location_uids" in payload_dict and payload_dict["location_uids"]:
            uids = payload_dict["location_uids"]
            locations = self._validate_locations(uids)
            terminal.locations.set(locations)

        if "evse_uids" in payload_dict and payload_dict["evse_uids"]:
            uids = payload_dict["evse_uids"]
            evses = self._validate_evses(uids)
            terminal.evses.set(evses)

        terminal.save()
        return terminal

    def _validate_locations(self, uids: list[str]) -> list[Location]:
        locations = []
        for uid in uids:
            try:
                location = Location.objects.get(uid=uid)
                locations.append(location)
            except Location.DoesNotExist:
                raise TerminalValidationError(f"Location with uid {uid} is invalid.")
        return locations

    def _validate_evses(self, uids: list[str]) -> list[Evse]:
        evses = []
        for uid in uids:
            try:
                evse = Evse.objects.get(uid=uid)
                evses.append(evse)
            except Evse.DoesNotExist:
                raise TerminalValidationError(f"Evse with uid {uid} is invalid.")
        return evses

    def _send_to_ptp(self, terminal: Terminal, method: str, payload: dict):
        credentials = terminal.credentials
        if not credentials or not credentials.url:
            logger.error(f"Terminal {terminal.terminal_id} has no credentials.")
            return

        ptp_role = credentials.roles.first()
        if not ptp_role:
            logger.error(f"Missing role for credentials {credentials.id} and terminal {terminal.terminal_id}")
            return
        

        sender = get_our_party(OcpiRolesEnum.CPO)
        if not sender:
            logger.error(f"Failed to get sender for terminal {terminal.terminal_id}")
            return

        url = f"{with_trailing_slash(credentials.url)}terminals/{terminal.terminal_id}"

        kwargs = {
            "data": payload,
            "url": url,
            "token_base64": credentials.theirs_base64(),
            "to_country_code": ptp_role.country_code,
            "to_party_id": ptp_role.party_id,
            "from_country_code": sender.country_code,
            "from_party_id": sender.party_id,
            "method": method.lower(),
            "credentials_id": credentials.id,
        }

        send_ocpi_request.apply_async(kwargs=kwargs)


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
