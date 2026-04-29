from logging import getLogger
from typing import Optional

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from ocpi22.choices import OcpiModuleEnum, EndpointRoleEnum
from ocpi22.credentials.util import find_endpoints_by_roles
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.location import Location, Evse
from ocpi22.payments.exceptions import (
    TerminalAlreadyExistsError,
    FinancialAdviceConfirmationAlreadyExistsError,
    FinancialAdviceConfirmationValidationError,
    TerminalValidationError,
)
from ocpi22.payments.models import Terminal, FinancialAdviceConfirmation
from ocpi22.payments.repositories import (
    TerminalRepository,
    FinancialAdviceConfirmationRepository,
)
from ocpi22.payments.schemas import TerminalIn, TerminalPutIn
from ocpi22.tasks import send_ocpi_request
from ocpiconnector.ocpi_identities import get_our_party
from util import with_trailing_slash
from webhooks.models import WebhookEvent, WebhookEventType
from webhooks.repository import WebhookRepository
from webhooks.services import WebhookEventService
from webhooks.tasks import execute_webhook_event as execute_webhook_event_task

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

    def put_terminal(self, terminal: Terminal, payload: TerminalPutIn) -> Terminal:
        terminal.invoice_base_url = (
            str(payload.invoice_base_url) if payload.invoice_base_url else None
        )
        terminal.last_updated = payload.last_updated

        locations, evses = self._resolve_locations_and_evses(
            payload.location_ids, payload.evse_uids
        )
        terminal.locations.set(locations)
        terminal.evses.set(evses)

        try:
            terminal.save()
        except DjangoValidationError as e:
            raise TerminalValidationError(e.messages[0]) from e
        return terminal

    def patch_terminal(self, terminal: Terminal, payload: TerminalIn) -> Terminal:
        payload_dict = payload.dict(exclude_unset=True)

        if "invoice_base_url" in payload_dict:
            url = payload_dict["invoice_base_url"]
            terminal.invoice_base_url = str(url) if url else None

        terminal.last_updated = timezone.now()

        if "location_ids" in payload_dict or "evse_uids" in payload_dict:
            loc_ids = payload_dict.get("location_ids", [])
            evse_uids = payload_dict.get("evse_uids", [])
            locations, evses = self._resolve_locations_and_evses(loc_ids, evse_uids)
            terminal.locations.set(locations)
            terminal.evses.set(evses)

        try:
            terminal.save()
        except DjangoValidationError as e:
            raise TerminalValidationError(e.messages[0]) from e
        return terminal

    def _check_missing_uids(self, uids: list[str], uids_db: set[str]) -> None:
        if not uids:
            return
        missing_uids = set(uids) - uids_db
        if missing_uids:
            raise TerminalValidationError(
                f"uids {', '.join(sorted(missing_uids))} are invalid."
            )

    def _validate_locations(self, uids: list[str]) -> list[Location]:
        locations = list(Location.objects.filter(uid__in=uids))
        uid_db = {loc.uid for loc in locations}
        self._check_missing_uids(uids, uid_db)
        return locations

    def _validate_evses(self, uids: list[str]) -> list[Evse]:
        evses = list(Evse.objects.filter(uid__in=uids).select_related("location"))
        uid_db = {evse.uid for evse in evses}
        self._check_missing_uids(uids, uid_db)
        return evses

    def _validate_evses_by_location(
        self, location_ids: set[str], evses: list[Evse]
    ) -> list[Evse]:
        evses_not_related_to_given_locations = sorted(
            evse.uid for evse in evses if evse.location.uid not in location_ids
        )
        if evses_not_related_to_given_locations:
            raise TerminalValidationError(
                f"Cannot update terminal, EVSEs {', '.join(evses_not_related_to_given_locations)} do not belong to the given locations."
            )

    def _validate_locations_ids_by_evses(
        self, location_ids: set[str], evses: list[Evse]
    ) -> list[Evse]:
        location_uids_by_evses = {evse.location.uid for evse in evses}
        locations_outside_given_evses = sorted(location_ids - location_uids_by_evses)
        if locations_outside_given_evses:
            raise TerminalValidationError(
                f"Cannot update terminal, Location ids {', '.join(locations_outside_given_evses)} are missing according to the given EVSEs."
            )

    def _resolve_locations_and_evses(
        self, location_ids: list[str], evse_uids: list[str]
    ) -> tuple[list[Location], list[Evse]]:
        if location_ids and not evse_uids:
            locations = self._validate_locations(location_ids)
            evses = list(
                Evse.objects.filter(location__uid__in=location_ids).select_related(
                    "location"
                )
            )
            loc_uids_with_evses = {evse.location.uid for evse in evses}
            locations_without_evses = sorted(set(location_ids) - loc_uids_with_evses)
            if locations_without_evses:
                raise TerminalValidationError(
                    f"Cannot assign locations with no EVSEs to the terminal. {', '.join(locations_without_evses)}"
                )
            return locations, evses

        elif evse_uids and not location_ids:
            evses = self._validate_evses(evse_uids)
            locations = list(
                {evse.location_id: evse.location for evse in evses}.values()
            )
            return locations, evses

        else:
            locations = self._validate_locations(location_ids)
            evses = self._validate_evses(evse_uids)

            location_ids_set = set(location_ids)
            self._validate_evses_by_location(location_ids_set, evses)
            self._validate_locations_ids_by_evses(location_ids_set, evses)
            return locations, evses

    def _send_to_ptp(
        self,
        terminal: Terminal,
        method: str,
        payload: "TerminalIn",
    ) -> None:
        if method == "put":
            data = {
                "location_ids": list(terminal.locations.values_list("uid", flat=True)),
                "evse_uids": list(terminal.evses.values_list("uid", flat=True)),
                "invoice_base_url": terminal.invoice_base_url,
                "last_updated": terminal.last_updated,
            }
        else:
            fields = payload.model_fields_set
            data: dict = {"last_updated": terminal.last_updated}
            if "location_ids" in fields or "evse_uids" in fields:
                data["location_ids"] = list(
                    terminal.locations.values_list("uid", flat=True)
                )
                data["evse_uids"] = list(terminal.evses.values_list("uid", flat=True))
            if "invoice_base_url" in fields:
                data["invoice_base_url"] = terminal.invoice_base_url
        credentials = terminal.credentials
        if not credentials or not credentials.url:
            logger.error(f"Terminal {terminal.terminal_id} has no credentials.")
            return

        ptp_role = credentials.roles.first()
        if not ptp_role:
            logger.warning(
                f"Missing role for credentials {credentials.id} and terminal {terminal.terminal_id}"
            )
            return

        endpoints = find_endpoints_by_roles(
            roles=(str(ptp_role.role),),
            ocpi_module=OcpiModuleEnum.PAYMENTS,
            endpoint_role=EndpointRoleEnum.RECEIVER.value,
        )

        url = None
        for endpoint in endpoints:
            endpoint_url, _, _, _, endpoint_credentials = endpoint
            if endpoint_credentials.id == credentials.id:
                url = endpoint_url
                break

        if not url:
            logger.warning(
                f"Failed to find PAYMENTS RECEIVER endpoint for terminal {terminal.terminal_id}"
            )
            return

        sender_party = get_our_party()
        if not sender_party:
            logger.error(f"Failed to get sender for terminal {terminal.terminal_id}")
            return

        url = f"{with_trailing_slash(url)}terminals/{terminal.terminal_id}"

        kwargs = {
            "data": data,
            "method": method.lower(),
            "url": url,
            "token_base64": credentials.theirs_base64(),
            "to_country_code": ptp_role.country_code,
            "to_party_id": ptp_role.party_id,
            "from_country_code": sender_party.country_code,
            "from_party_id": sender_party.party_id,
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

        event = self._create_fac_webhook_event(fac)
        if event:
            transaction.on_commit(lambda: execute_webhook_event_task.delay(event.id))

        return fac

    def _create_fac_webhook_event(
        self, fac: FinancialAdviceConfirmation
    ) -> Optional[WebhookEvent]:
        webhook = WebhookRepository.get_fac_webhook()
        if not webhook:
            return None

        payload = {
            "fac_id": fac.fac_id,
            "authorization_reference": fac.authorization_reference,
            "total_cost_excl_vat": fac.total_cost_excl_vat,
            "total_cost_incl_vat": fac.total_cost_incl_vat,
            "currency": fac.currency,
            "eft_data": fac.eft_data,
            "capture_status_code": fac.capture_status_code,
            "capture_status_message": fac.capture_status_message,
            "last_updated": fac.last_updated,
        }
        try:
            with transaction.atomic():
                return WebhookEventService.create_event(
                    webhook=webhook,
                    event_type=WebhookEventType.FAC_CREATED,
                    payload=payload,
                )
        except Exception:
            logger.error(
                "Failed to create FAC webhook event for fac %s",
                fac.fac_id,
                exc_info=True,
            )
            return None
