# TODO refactor this to have ddomain speicific services
from django.db.models import QuerySet
from rest_framework.exceptions import ValidationError

from ocpi22.cpo.repositories import SolidTariffRepository
from ocpi22.cpo.schemas import LocationIn
from ocpi22.locations.serializers import LocationSerializer221
from ocpi22.models.credentials import Credentials, CredentialsRole
from ocpi22.models.location import Evse, Location
from ocpi22.ocpi.util import remove_none_values_recursively_from_dict
from ocpiconnector.party import Party


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


class LocationService:
    solid_tariff_repository = SolidTariffRepository()

    @staticmethod
    def get_allowed_locations_queryset(
        credentials: Credentials | None, queryset: QuerySet
    ) -> QuerySet:
        if credentials and credentials.allowed_locations:
            return queryset.filter(uid__in=credentials.allowed_locations)
        return queryset

    def update_tariff_in_request_payload(self, location: LocationIn):
        tariffs = []
        for e in location.evses:
            for c in e.connectors:
                tariff_ids = c.tariff_ids
                for t in tariff_ids:
                    solid_tariff = (
                        self.solid_tariff_repository.get_latest_with_external_id(
                            external_id=t
                        )
                    )
                    if solid_tariff:
                        tariffs.append(solid_tariff.ocpi_tariff.uid)
                c.tariff_ids = tariffs
        return location

    def get_data_from_request_payload(self, location: LocationIn):
        location = self.update_tariff_in_request_payload(location)

        data = location.model_dump(by_alias=True)

        country_code = data.get("country_code")
        party_id = data.get("party_id")
        ocpi_master = Party.from_str(f"{country_code}*{party_id}").get_role_if_exists()
        data["ocpi_master"] = ocpi_master

        data = remove_none_values_recursively_from_dict(data)

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
