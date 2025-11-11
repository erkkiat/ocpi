from django.db.models import Q, QuerySet, Max, Prefetch

from ocpi22.models.credentials import Credentials
from ocpi22.models.location import Evse, Connector
from ocpi22.models.tariff import SolidTariff, Tariff
from ocpiconnector.party import Party


class SolidTariffRepository:
    def get_latest_with_unique_external_id_and_msp(self) -> QuerySet:
        latest_tariffs = (
            SolidTariff.objects.filter(Q(msp__isnull=True) | Q(msp__id__isnull=False))
            .values("external_id", "msp_id")
            .annotate(latest_created=Max("created_at"))
        )

        return SolidTariff.objects.filter(
            Q(
                external_id__in=[entry["external_id"] for entry in latest_tariffs],
                created_at__in=[entry["latest_created"] for entry in latest_tariffs],
            )
        )

    def exists(self, **kwargs) -> bool:
        return SolidTariff.objects.filter(**kwargs).exists()

    def get_latest_with_external_id(self, external_id) -> SolidTariff | None:
        try:
            return SolidTariff.objects.filter(external_id=external_id).latest(
                "created_at"
            )
        except SolidTariff.DoesNotExist:
            return None

    @staticmethod
    def find_by_ocpi_tariff_id(ocpi_tariff_id: str) -> SolidTariff | None:
        try:
            return SolidTariff.objects.filter(ocpi_tariff__uid=ocpi_tariff_id).latest(
                "created_at"
            )
        except SolidTariff.DoesNotExist:
            return None


class CredentialsRepository:
    @staticmethod
    def get_evses_by_party(credentials: Credentials, party: Party) -> QuerySet:
        if not credentials:
            return None

        allowed_locations = credentials.allowed_locations

        location_based_filter = {
            "location__ocpi_master__party_id": party.party_id,
            "location__ocpi_master__country_code": party.country_code,
            "location__roaming_enabled": True,
        }

        if allowed_locations:
            location_based_filter["location__uid__in"] = allowed_locations

        return Evse.objects.filter(**location_based_filter).prefetch_related(
            Prefetch(
                "connectors",
                queryset=Connector.objects.prefetch_related(
                    Prefetch("tariff_ids", queryset=Tariff.objects.only("uid"))
                ),
                to_attr="connectors_with_tariffs",
            )
        )
