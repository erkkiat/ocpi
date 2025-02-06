from django.db import transaction

from ocpi22.cpo.repositories import SolidTariffRepository
from ocpi22.models.tariff import SolidTariff, Tariff, TariffElement, PriceComponent


class SolidTariffService:
    solid_tariff_repository = SolidTariffRepository()

    def get_all_latest_solid_tariffs(self):
        return self.solid_tariff_repository.get_latest_with_unique_external_id_and_msp()

    def create(self, validated_data: dict) -> dict:
        from ocpi22.cpo.serializers import (
            CurrencySerializer,
            PriceKwhSerializer,
            PriceMinSerializer,
            PriceFlatSerializer,
            VatSerializer,
            ParkingPricePerMinSerializer,
        )

        per_kwh = validated_data.get(PriceKwhSerializer.key)
        per_min = validated_data.get(PriceMinSerializer.key)
        flat = validated_data.get(PriceFlatSerializer.key)
        parking_price = validated_data.get(ParkingPricePerMinSerializer.key)
        vat = validated_data.get(VatSerializer.key)
        currency = validated_data.get(CurrencySerializer.key)
        grace_period = validated_data.get("parking_grace_period")

        operator = validated_data.pop("ocpi_master")

        validated_data["operator"] = operator
        msp = validated_data.get("msp")
        external_id = validated_data.get("external_id")

        per_hr = float(per_min) * 60 if per_min else None
        parking_price_per_hr = float(parking_price) * 60 if parking_price else None

        if SolidTariff.is_duplicate(**validated_data):
            solid_tariff = SolidTariff.objects.filter(**validated_data).first()
            tariff = Tariff.objects.filter(uid=external_id).first()
            return {"tariff": tariff, "solid_tariff": solid_tariff, "created": False}

        with transaction.atomic():
            # Todo: This is going to be immutable in the upcoming PRs
            tariff = Tariff.objects.filter(uid=external_id)

            if not tariff.exists():
                tariff = Tariff.objects.create(
                    uid=external_id,
                    ocpi_master=validated_data.get("ocpi_master"),
                    currency=currency,
                )
            else:
                tariff = tariff.first()
            te, _created = TariffElement.objects.get_or_create(tariff=tariff)
            if per_kwh:
                PriceComponent.objects.update_or_create(
                    tariff_element=te,
                    type="ENERGY",
                    defaults={"price": per_kwh, "vat": vat, "step_size": 1},
                )
            if per_min:
                PriceComponent.objects.update_or_create(
                    tariff_element=te,
                    type="TIME",
                    defaults={"price": per_hr, "vat": vat, "step_size": 1},
                )
            if flat:
                PriceComponent.objects.update_or_create(
                    tariff_element=te,
                    type="FLAT",
                    defaults={"price": flat, "vat": vat, "step_size": 1},
                )
            if parking_price:
                PriceComponent.objects.update_or_create(
                    tariff_element=te,
                    type="PARKING_TIME",
                    defaults={
                        "price": parking_price_per_hr,
                        "vat": vat,
                        "step_size": 1,
                    },
                )

            solid_tariff = SolidTariff(
                external_id=external_id,
                currency=currency,
                price_per_kwh=per_kwh,
                price_per_min=per_min,
                price_flat=flat,
                parking_price_per_min=parking_price,
                parking_grace_period=grace_period,
                vat_percentage=vat,
                msp=msp,
                operator=operator,
            )
            solid_tariff.save()

        return {"tariff": tariff, "solid_tariff": solid_tariff, "created": True}
