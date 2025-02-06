from django.db.models import Subquery, OuterRef, Q, QuerySet

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
        )
