import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction

from ocpi22.cpo.repositories import SolidTariffRepository
from ocpi22.models.tariff import SolidTariff, Tariff, TariffElement, PriceComponent


class SolidTariffService:
    solid_tariff_repository = SolidTariffRepository()

    def get_all_latest_solid_tariffs(self):
        return self.solid_tariff_repository.get_latest_with_unique_external_id_and_msp()

    def create(self, validated_data: dict) -> SolidTariff | None:
        if validated_data.get("currency") is None:
            raise ValidationError("Currency is required")
        if validated_data.get("ocpi_master") is None:
            raise ValidationError("OCPI Master is required")

        operator = validated_data.pop("ocpi_master")
        validated_data["operator"] = operator
        (
            per_kwh,
            per_min,
            per_hour,
            flat,
            parking_price_per_min,
            parking_price_per_hr,
            vat,
            currency,
            grace_period,
        ) = self._extract_pricing_data(validated_data)

        per_hr = self._convert_to_hourly(per_min) if not per_hour else per_hour
        parking_price_per_hr = (
            self._convert_to_hourly(parking_price_per_min)
            if not parking_price_per_hr
            else parking_price_per_hr
        )

        self._set_missing_fields(validated_data)

        duplicate_solid_tariff = SolidTariff.objects.get_if_exists(**validated_data)

        old_solid_tariff = self.solid_tariff_repository.get_latest_with_external_id(
            validated_data["external_id"]
        )

        if duplicate_solid_tariff:
            if duplicate_solid_tariff.pk == old_solid_tariff.pk:
                duplicate_solid_tariff.ocpi_tariff.post_process_after_update_or_create()
                return duplicate_solid_tariff

        saved_solid_tariff = self._create_new_tariff(
            validated_data,
            operator,
            currency,
            per_kwh,
            per_min,
            per_hr,
            flat,
            parking_price_per_min,
            parking_price_per_hr,
            vat,
            grace_period,
        )

        if old_solid_tariff:
            self._send_updates_to_attached_connectors(
                old_solid_tariff, saved_solid_tariff
            )

        return saved_solid_tariff

    def _extract_pricing_data(self, validated_data):
        from ocpi22.cpo.serializers import (
            CurrencySerializer,
            PriceKwhSerializer,
            PriceMinSerializer,
            PriceFlatSerializer,
            VatSerializer,
            PriceHourSerializer,
            ParkingPricePerMinSerializer,
            ParkingPricePerHourSerializer,
        )

        per_kwh = validated_data.get(PriceKwhSerializer.key)
        per_min = validated_data.get(PriceMinSerializer.key)
        per_hour = validated_data.get(PriceHourSerializer.key)
        flat = validated_data.get(PriceFlatSerializer.key)
        parking_price_per_min = validated_data.get(ParkingPricePerMinSerializer.key)
        parking_price_per_hr = validated_data.get(ParkingPricePerHourSerializer.key)
        vat = validated_data.get(VatSerializer.key)
        currency = validated_data.get(CurrencySerializer.key)
        grace_period = validated_data.get("parking_grace_period")

        return (
            per_kwh,
            per_min,
            per_hour,
            flat,
            parking_price_per_min,
            parking_price_per_hr,
            vat,
            currency,
            grace_period,
        )

    def _convert_to_hourly(self, per_minute_value):
        try:
            return float(per_minute_value) * 60 if per_minute_value else None
        except (ValueError, TypeError):
            return None

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
                validated_data.pop(key, None)

    def _create_new_tariff(
        self,
        validated_data,
        operator,
        currency,
        per_kwh,
        per_min,
        per_hr,
        flat,
        parking_price_per_min,
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

            ocpi_tariff.post_process_after_update_or_create()

            return SolidTariff.objects.create(
                external_id=external_id,
                currency=currency,
                price_per_kwh=per_kwh,
                price_per_min=per_min,
                price_per_hr=per_hr,
                price_flat=flat,
                parking_price_per_min=parking_price_per_min,
                parking_price_per_hr=parking_price_per_hr,
                parking_grace_period=grace_period,
                vat_percentage=vat,
                ocpi_tariff=ocpi_tariff,
                msp=msp,
                last_updated=last_updated,
                operator=operator,
            )

    def _get_ocpi_uid(self):
        # TODO: MSP specific ocpi tariffs requirement is not satisfied here.
        #  check https://github.com/solidroam/ocpiconnector/issues/253 for more details.
        return str(uuid.uuid4())

    def _create_ocpi_tariff(self, operator, currency) -> Tariff:
        random_ocpi_tariff_id = self._get_ocpi_uid()
        tariff = Tariff.objects.create(
            uid=random_ocpi_tariff_id, ocpi_master=operator, currency=currency
        )
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

    def _send_updates_to_attached_connectors(self, old_solid_tariff, new_solid_tariff):
        for connector in old_solid_tariff.ocpi_tariff.connectors.all():
            connector.tariff_ids.remove(old_solid_tariff.ocpi_tariff)
            connector.tariff_ids.add(new_solid_tariff.ocpi_tariff)
            connector.save()
            connector.evse.location.post_process_after_update_or_create()
