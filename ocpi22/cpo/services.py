import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from django.db import transaction

from ocpi22.cpo.repositories import SolidTariffRepository
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.tariff import SolidTariff, Tariff, TariffElement, PriceComponent


class SolidTariffService:
    solid_tariff_repository = SolidTariffRepository()

    def get_all_latest_solid_tariffs(self):
        return self.solid_tariff_repository.get_latest_with_unique_external_id_and_msp()

    def create(self, validated_data: dict) -> SolidTariff:
        operator = validated_data.pop("ocpi_master")
        validated_data["operator"] = operator

        per_kwh, per_min, flat, parking_price, vat, currency, grace_period = (
            self._extract_pricing_data(validated_data)
        )

        per_hr = self._convert_to_hourly(per_min)
        parking_price_per_hr = self._convert_to_hourly(parking_price)

        self._set_missing_fields(validated_data)

        solid_tariff = self._get_existing_tariff(validated_data)
        if solid_tariff:
            return solid_tariff

        return self._create_new_tariff(
            validated_data,
            operator,
            currency,
            per_kwh,
            per_min,
            per_hr,
            flat,
            parking_price,
            parking_price_per_hr,
            vat,
            grace_period,
        )

    def _extract_pricing_data(self, validated_data):
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

        return per_kwh, per_min, flat, parking_price, vat, currency, grace_period

    def _convert_to_hourly(self, per_minute_value):
        return float(per_minute_value) * 60 if per_minute_value else None

    def _set_missing_fields(self, validated_data):
        expected_keys = [
            "price_per_kwh",
            "price_per_min",
            "price_flat",
            "parking_price_per_min",
            "vat_percentage",
            "parking_grace_period",
            "msp",
        ]
        for key in expected_keys:
            if validated_data.get(key) is None:
                validated_data[f"{key}__isnull"] = True

    def _get_existing_tariff(self, validated_data) -> SolidTariff | None:
        if self.solid_tariff_repository.exists(**validated_data):
            return SolidTariff.objects.get(**validated_data)
        if validated_data.get("msp") is not None:
            temp_validated_data = validated_data.copy()
            temp_validated_data.pop("msp")
            return SolidTariff.objects.get(**temp_validated_data)
        return None

    def _create_new_tariff(
        self,
        validated_data,
        operator,
        currency,
        per_kwh,
        per_min,
        per_hr,
        flat,
        parking_price,
        parking_price_per_hr,
        vat,
        grace_period,
    ) -> SolidTariff:
        external_id = validated_data.get("external_id")
        last_updated = validated_data.get(
            "last_updated", datetime.now(tz=ZoneInfo("UTC"))
        )
        msp = validated_data.get("msp")

        with transaction.atomic():
            ocpi_tariff = self._create_ocpi_tariff(operator, currency)

            self._create_price_components(
                ocpi_tariff, per_kwh, per_hr, flat, parking_price_per_hr, vat
            )

            return SolidTariff.objects.create(
                external_id=external_id,
                currency=currency,
                price_per_kwh=per_kwh,
                price_per_min=per_min,
                price_flat=flat,
                parking_price_per_min=parking_price,
                parking_grace_period=grace_period,
                vat_percentage=vat,
                ocpi_tariff=ocpi_tariff,
                msp=msp,
                last_updated=last_updated,
                operator=operator,
            )

    def _create_ocpi_tariff(self, operator, currency) -> Tariff:
        random_ocpi_tariff_id = str(uuid.uuid4())
        tariff = Tariff.objects.create(
            uid=random_ocpi_tariff_id, ocpi_master=operator, currency=currency
        )
        TariffElement.objects.get_or_create(tariff=tariff)
        return tariff

    def _create_price_components(
        self, tariff, per_kwh, per_hr, flat, parking_price_per_hr, vat
    ):
        tariff_element, _created = TariffElement.objects.get_or_create(tariff=tariff)

        price_data = [
            ("ENERGY", per_kwh),
            ("TIME", per_hr),
            ("FLAT", flat),
            ("PARKING_TIME", parking_price_per_hr),
        ]

        for price_type, price in price_data:
            if price:
                PriceComponent.objects.create(
                    tariff_element=tariff_element,
                    type=price_type,
                    price=price,
                    vat=vat,
                    step_size=1,
                )

    def delete_by_msp_and_external_id(
        self, msp: CredentialsRole, external_id: str
    ) -> bool:
        return self.solid_tariff_repository.delete_all_by_external_id_msp(
            external_id, msp
        )

    def delete_by_external_id(self, external_id: str) -> bool:
        return self.solid_tariff_repository.delete_all_by_external_id(external_id)
