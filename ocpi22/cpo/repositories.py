from django.db.models import Q, QuerySet, Max

from ocpi22.models.tariff import SolidTariff


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
