# TODO refactor this to have ddomain speicific services
import zoneinfo

from django.conf import settings
from django.db.models import QuerySet
from rest_framework.exceptions import ValidationError

from ocpi22.credentials.services import CredentialsService
from ocpi22.cpo.services import SolidTariffService
from ocpi22.models.credentials import Credentials
from ocpi22.models.location import Evse
import logging
from ocpi22.cpo.repositories import SolidTariffRepository, CredentialsRepository
from ocpi22.cpo.schemas import LocationIn
from ocpi22.locations.serializers import LocationSerializer221
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.location import Location
from ocpiconnector.party import Party
from integrations.hubject.services import HubjectService

logger = logging.getLogger(__name__)


class EvseServices:
    @staticmethod
    def ocpp_to_evse_status(status: str):
        match status:
            case "AVAILABLE":
                return Evse.AVAILABLE
            case "PREPARING":
                return Evse.CHARGING
            case "CHARGING":
                return Evse.CHARGING
            case "SUSPENDEDEV":
                return Evse.CHARGING
            case "SUSPENDEDEVSE":
                return Evse.CHARGING
            case "FINISHING":
                return Evse.CHARGING
            case "RESERVED":
                return Evse.RESERVED
            case "FAULTED":
                return Evse.OUTOFORDER
            case "UNAVAILABLE":
                return Evse.CHARGING
            case _:
                raise ValueError(f"Invalid OCPP status [{status}] found")

    @staticmethod
    def send_status_updates(evse: Evse) -> None:
        last_updated_serialized = evse.last_updated.replace(
            tzinfo=zoneinfo.ZoneInfo("UTC")
        ).isoformat()
        data = {"status": evse.status, "last_updated": last_updated_serialized}
        location = evse.location
        location.send_all_updates(
            data=data,
            method="patch",
            path_components=[
                location.ocpi_master.country_code,
                location.ocpi_master.party_id,
                location.uid,
                evse.uid,
            ],
        )

        if settings.ENABLE_HUBJECT:
            role = CredentialsRepository.find_hubject_credentials_role()
            if not role:
                logger.error("Hubject credentials role not found")
                return
            credentials = role.credentials if role else None
            if CredentialsService.is_evse_allowed(credentials, evse):
                HubjectService.post_eroaming_push_evse_status(evse)


class LocationService:
    solid_tariff_repository = SolidTariffRepository()
    solid_tariff_service = SolidTariffService()

    @staticmethod
    def get_allowed_locations_queryset(
        credentials: Credentials | None, queryset: QuerySet
    ) -> QuerySet:
        if credentials and credentials.allowed_locations:
            return queryset.filter(uid__in=credentials.allowed_locations)
        return queryset

    def update_tariff_in_payload(self, location: LocationIn):
        for e in location.evses:
            for c in e.connectors:
                tariffs = []
                tariff_ids = c.tariff_ids
                for t in tariff_ids or []:
                    solid_tariff = (
                        self.solid_tariff_repository.get_latest_with_external_id(
                            external_id=t
                        )
                    )
                    if solid_tariff:
                        tariffs.append(solid_tariff.ocpi_tariff.uid)
                    else:
                        raise ValidationError(
                            f"SolidTariff with external_id {t} not found"
                        )
                c.tariff_ids = tariffs
        return location

    def get_data_from_request_payload(self, location: LocationIn):
        location = self.update_tariff_in_payload(location)

        data = location.model_dump(by_alias=True, exclude_unset=True)

        country_code = data.get("country_code")
        party_id = data.get("party_id")
        ocpi_master = Party.from_str(f"{country_code}*{party_id}").get_role_if_exists()
        data["ocpi_master"] = ocpi_master

        return data

    def create_location(self, location: LocationIn, credentials_role: CredentialsRole):
        data = self.get_data_from_request_payload(location)

        serializer = LocationSerializer221(
            data=data,
            partial=False,
            context={
                "party": credentials_role.get_party(),
                "credentialsrole": credentials_role,
            },
        )

        if serializer.is_valid():
            location = serializer.create(serializer.validated_data)
            location.post_process_after_update_or_create()
            return LocationSerializer221(instance=location).data
        raise ValidationError(serializer.errors)

    def update_location(
        self,
        location: LocationIn,
        credentials_role: CredentialsRole,
        existing_location: Location,
    ):
        data = self.get_data_from_request_payload(location)

        serializer = LocationSerializer221(
            instance=existing_location,
            data=data,
            partial=False,
            context={
                "party": credentials_role.get_party(),
                "credentialsrole": credentials_role,
            },
        )

        if serializer.is_valid():
            saved_location = serializer.update(
                existing_location, serializer.validated_data
            )
            saved_location.post_process_after_update_or_create()
            return serializer.data
        raise ValidationError(serializer.errors)

    def convert_ocpi_tariff_ids_to_solid_tariff_ids(self, location: dict):
        for evse in location["evses"]:
            for connector in evse["connectors"]:
                if connector.get("tariff_ids"):
                    solid_tariff_ids = []
                    for tariff_id in connector["tariff_ids"]:
                        solid_tariff_external_id = self.solid_tariff_service.get_solid_tariff_external_id_by_ocpi_tariff_uid(
                            tariff_id.upper()
                        )
                        if solid_tariff_external_id:
                            solid_tariff_ids.append(solid_tariff_external_id)
                        else:
                            raise ValidationError(
                                f"SolidTariff for OCPI tariff '{tariff_id}' not found"
                            )
                    connector["tariff_ids"] = solid_tariff_ids
        return location
