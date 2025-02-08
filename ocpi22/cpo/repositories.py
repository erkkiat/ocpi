from django.db.models import Subquery, OuterRef, Q, QuerySet

from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.tariff import SolidTariff, Tariff


class SolidTariffRepository:
    def get_latest_with_unique_external_id_and_msp(self) -> QuerySet:
        return SolidTariff.objects.filter(
            id=Subquery(
                SolidTariff.objects.filter(external_id=OuterRef("external_id"))
                .filter(Q(msp__id=OuterRef("msp__id")) | Q(msp__isnull=True))
                .order_by("-created")
                .values("id")[:1]
            )
        ).all()

    def exists(self, **kwargs) -> bool:
        expected_keys = [
            "price_per_kwh",
            "price_per_min",
            "price_flat",
            "parking_price_per_min",
            "vat_percentage",
            "parking_grace_period",
        ]

        for key in expected_keys:
            if kwargs.get(key) is None:
                kwargs[f"{key}__isnull"] = True
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


class TariffRepository:
    # TODO: I want to avoid coupling SolidTariffRepository here.
    solid_tariff_repository = SolidTariffRepository()

    def get_latest_tariffs_from_solid_tariffs(self):
        latest_solid_tariffs = (
            self.solid_tariff_repository.get_latest_with_unique_external_id_and_msp()
        )
        return (
            Tariff.objects.filter(
                id__in=latest_solid_tariffs.values_list("ocpi_tariff_id", flat=True)
            )
            .exclude(archived=True)
            .order_by("created")
        )
