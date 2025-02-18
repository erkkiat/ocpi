from django.db.models import Q, QuerySet, Max

from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.tariff import SolidTariff


class SolidTariffRepository:
    def get_latest_with_unique_external_id_and_msp(self) -> QuerySet:
        latest_tariffs = (
            SolidTariff.objects.filter(Q(msp__isnull=True) | Q(msp__id__isnull=False))
            .values("external_id", "msp_id")
            .annotate(latest_created=Max("created"))
        )

        return SolidTariff.objects.filter(
            Q(
                external_id__in=[entry["external_id"] for entry in latest_tariffs],
                created__in=[entry["latest_created"] for entry in latest_tariffs],
            )
        )

    def exists(self, **kwargs) -> bool:
        return SolidTariff.objects.filter(**kwargs).exists()

    def delete_all_by_external_id_msp(
        self, external_id: str, msp: CredentialsRole
    ) -> bool:
        deleted, _rows_count = SolidTariff.objects.filter(
            external_id=external_id, msp=msp
        ).delete()
        return deleted

    def delete_all_by_external_id(self, external_id: str) -> bool:
        deleted, _rows_count = SolidTariff.objects.filter(
            external_id=external_id
        ).delete()
        return deleted
