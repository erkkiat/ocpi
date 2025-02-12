from django.db.models import Subquery, OuterRef, Q, QuerySet

from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.tariff import SolidTariff


class SolidTariffRepository:
    def get_latest_with_unique_external_id_and_msp(self) -> QuerySet:
        return SolidTariff.objects.filter(
            id=Subquery(
                SolidTariff.objects.filter(external_id=OuterRef("external_id"))
                .filter(Q(msp__id=OuterRef("msp__id")) | Q(msp__isnull=True))
                .order_by("-created_at")
                .values("id")[:1]
            )
        ).all()

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
