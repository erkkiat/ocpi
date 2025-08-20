import logging
import typing
import uuid
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import pytz
from django.core.exceptions import ValidationError
from django.db import transaction

from ocpi22.cpo.repositories import SolidTariffRepository
from ocpi22.models.cdrlocation import CdrLocation
from ocpi22.models.session import ChargingPeriodSerializer
from ocpi22.models.tariff import SolidTariff, Tariff, TariffElement, PriceComponent
from ocpi22.ocpi.util import generate_cdr_uid
from ocpi22.models.session import Session

logger = logging.getLogger(__name__)

if typing.TYPE_CHECKING:
    from ocpi22.models.cdr import Cdr


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
        per_kwh, per_min, flat, parking_price, vat, currency, grace_period = (
            self._extract_pricing_data(validated_data)
        )

        per_hr = self._convert_to_hourly(per_min)
        parking_price_per_hr = self._convert_to_hourly(parking_price)

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
            parking_price,
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

            ocpi_tariff.post_process_after_update_or_create()

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


class CdrService:
    @classmethod
    def _get_charging_periods(cls, session: Session) -> list:
        charging_periods_json = ChargingPeriodSerializer(
            session.chargingperiods, many=True
        ).data

        if not session.chargingperiods.exists():
            logger.warning(
                f"No charging periods found for session {session.uid} to create CDR."
            )
            session.update_charging_periods(
                kwh=session.kwh, timestamp=session.start_date_time
            )
            charging_periods_json = ChargingPeriodSerializer(
                session.chargingperiods.all(), many=True
            ).data

        return charging_periods_json

    @classmethod
    def _get_cdr(cls, session_id: str) -> Optional["Cdr"]:
        from ocpi22.models.cdr import Cdr

        return Cdr.objects.filter(session_id=session_id).first()

    @classmethod
    def _get_cdr_tariffs(cls, charging_periods_json, standard) -> list[Tariff]:
        cdr_tariffs = []
        if isinstance(charging_periods_json, dict):
            charging_periods_json = [charging_periods_json]
        for charging_period in charging_periods_json:
            tariff_id = charging_period.get("tariff_id")
            if tariff_id:
                tariff = Tariff.objects.get_if_exists(uid=tariff_id)
                if tariff:
                    cdr_tariffs.append(tariff)
                else:
                    logger.warning(f"Tariff with uid {tariff_id} not found.")
        if not cdr_tariffs:
            logger.warning(
                "Charging period does not have a tariff_id, using default tariffs"
            )
            cdr_tariffs = list(Tariff.get_default_tariffs(standard).all())

        return cdr_tariffs

    @classmethod
    def _create_cdr(cls, session: Session) -> Optional["Cdr"]:
        from ocpi22.models.cdr import Cdr

        cdr_location = CdrLocation.get_or_create_from_session(session)
        charging_periods_json = cls._get_charging_periods(session)
        cdr_tariffs = cls._get_cdr_tariffs(
            charging_periods_json, session.connector.standard
        )

        cdr = Cdr.objects.create(
            uid=generate_cdr_uid(),
            start_date_time=session.start_date_time,
            end_date_time=session.end_date_time,
            session_id=session.uid,
            cdr_location=cdr_location,
            cdr_token=session.cdr_token,
            charging_periods=charging_periods_json,
            auth_method=session.auth_method,
            authorization_reference=session.authorization_reference,
            currency=session.currency,
            total_cost_excl_vat=session.total_cost_excl_vat or 0.0,
            total_cost_incl_vat=session.total_cost_incl_vat or 0.0,
            total_energy=session.kwh,
            credentials=session.credentials,
            ocpi_master=session.ocpi_master,
            billed_to=session.billed_to,
            last_updated=datetime.now(pytz.utc),
        )

        cdr.tariffs.set(cdr_tariffs)

        return cdr

    @classmethod
    def get_or_create_cdr(cls, session: Session) -> Optional["Cdr"]:
        if not session.connector:
            logging.error(
                f"Not creating a CDR from Session {session.uid} since no Connector is specified"
            )
            return None

        cdr = cls._get_cdr(session.uid)
        if cdr:
            return cdr

        if session.total_cost_excl_vat is None:
            logger.warning(f"Session {session} has no total cost")
        if not session.end_date_time:
            session.end_date_time = datetime.now(pytz.utc)

        cdr = cls._create_cdr(session)

        cdr.send_updates()

        return cdr
