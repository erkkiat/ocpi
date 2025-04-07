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
