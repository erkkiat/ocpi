import logging
from decimal import Decimal, InvalidOperation
import typing
import uuid
from datetime import datetime
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

import pytz
from django.conf import settings
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.db import transaction
from rest_framework.exceptions import ValidationError as RestFrameworkValidationError

from ocpi22.cpo.repositories import SolidTariffRepository
from webhooks.models import WebhookEvent, WebhookEventType
from webhooks.repository import WebhookRepository
from webhooks.services import WebhookEventService
from webhooks.tasks import execute_webhook_event as execute_webhook_event_task
from ocpi22.models.cdrlocation import CdrLocation
from ocpi22.models.displaytext import DisplayText
from ocpi22.models.session import ChargingPeriodSerializer
from ocpi22.models.tariff import SolidTariff, Tariff, TariffElement, PriceComponent
from ocpi22.ocpi.util import generate_cdr_uid
from ocpi22.models.session import Session

logger = logging.getLogger(__name__)


class TariffAltTextGenerator:
    _LANGUAGES: Tuple[str, ...] = ("en", "fr", "nl")
    _LABELS = {
        "en": {
            "hour_unit": "h",
            "time_suffix": " charging",
            "flat_suffix": " starting fee",
            "parking_suffix": " parking",
            "parking_grace": " parking after {minutes}min",
        },
        "fr": {
            "hour_unit": "h",
            "time_suffix": " recharge",
            "flat_suffix": " frais de démarrage",
            "parking_suffix": " stationnement",
            "parking_grace": " stationnement après {minutes}min",
        },
        "nl": {
            "hour_unit": "u",
            "time_suffix": " opladen",
            "flat_suffix": " startkost",
            "parking_suffix": " parkeren",
            "parking_grace": " parkeren na {minutes}min",
        },
    }

    @staticmethod
    def _apply_vat(amount: float, vat: float) -> float:
        return float(amount) * (1 + float(vat) / 100)

    @classmethod
    def _format_amount(cls, amount: float, currency: str, language: str) -> str:
        decimal_sep = "." if language == "en" else ","
        formatted = f"{amount:.2f}".replace(".", decimal_sep)
        if currency == "EUR":
            return f"{formatted}€" if language == "fr" else f"€{formatted}"
        return f"{currency} {formatted}"

    @classmethod
    def _format_rate(
        cls, amount: float, unit: str, currency: str, language: str
    ) -> str:
        return f"{cls._format_amount(amount, currency, language)}/{unit}"

    @classmethod
    def _build_for_language(
        cls,
        language: str,
        *,
        per_kwh: Optional[float],
        per_hr: Optional[float],
        flat: Optional[float],
        parking_per_hr: Optional[float],
        parking_grace_minutes: Optional[int],
        currency: str,
        vat: float,
    ) -> str:
        labels = cls._LABELS[language]
        components: List[str] = []

        if per_kwh is not None:
            components.append(
                cls._format_rate(
                    cls._apply_vat(per_kwh, vat), "kWh", currency, language
                )
            )

        if per_hr is not None:
            components.append(
                cls._format_rate(
                    cls._apply_vat(per_hr, vat), labels["hour_unit"], currency, language
                )
                + labels["time_suffix"]
            )

        if flat is not None:
            components.append(
                cls._format_amount(cls._apply_vat(flat, vat), currency, language)
                + labels["flat_suffix"]
            )

        if parking_per_hr is not None:
            parking_rate = cls._format_rate(
                cls._apply_vat(parking_per_hr, vat),
                labels["hour_unit"],
                currency,
                language,
            )
            if parking_grace_minutes and parking_grace_minutes > 0:
                components.append(
                    parking_rate
                    + labels["parking_grace"].format(minutes=parking_grace_minutes)
                )
            else:
                components.append(parking_rate + labels["parking_suffix"])

        return " + ".join(components)

    @classmethod
    def build(
        cls,
        *,
        per_kwh: Optional[float],
        per_hr: Optional[float],
        flat: Optional[float],
        parking_per_hr: Optional[float],
        parking_grace_minutes: Optional[int],
        currency: str,
        vat: float,
    ) -> List[Tuple[str, str]]:
        if not any(
            price is not None for price in (per_kwh, per_hr, flat, parking_per_hr)
        ):
            raise ValueError(
                "At least one price component must be set (per_kwh, per_hr, flat, or parking_per_hr)"
            )

        return [
            (
                language,
                cls._build_for_language(
                    language,
                    per_kwh=per_kwh,
                    per_hr=per_hr,
                    flat=flat,
                    parking_per_hr=parking_per_hr,
                    parking_grace_minutes=parking_grace_minutes,
                    currency=currency,
                    vat=vat,
                ),
            )
            for language in cls._LANGUAGES
        ]


if typing.TYPE_CHECKING:
    from ocpi22.models.cdr import Cdr


class SolidTariffService:
    solid_tariff_repository = SolidTariffRepository()

    @staticmethod
    def has_price_components(
        per_kwh: Optional[float],
        per_hr: Optional[float],
        flat: Optional[float],
        parking_per_hr: Optional[float],
    ) -> bool:
        return any(
            price is not None for price in (per_kwh, per_hr, flat, parking_per_hr)
        )

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

        per_hr = self._convert_to_hourly(per_min) if per_hour is None else per_hour
        parking_price_per_hr = (
            self._convert_to_hourly(parking_price_per_min)
            if parking_price_per_hr is None
            else parking_price_per_hr
        )

        # The Payter terminal requires a non-empty tariff_alt_text, which we
        # build from the price fields below. A SolidTariff with no price
        # components would produce an empty alt_text and break the terminal,
        # so reject it here before any DB writes happen.
        if not self.has_price_components(per_kwh, per_hr, flat, parking_price_per_hr):
            raise ValidationError(
                "At least one of price_per_kwh, price_per_min/hr, price_flat, "
                "or parking_price_per_min/hr is required"
            )

        validated_data["price_per_hr"] = per_hr
        validated_data["parking_price_per_hr"] = parking_price_per_hr

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

        if settings.ENABLE_HUBJECT:
            from integrations.hubject.services import HubjectService

            service = HubjectService()
            try:
                pricing_payload = service.get_pricing_product_insert_payload(
                    saved_solid_tariff
                )
                service.post_pricing_products(pricing_payload)
            except (ValueError, ValidationError):
                logger.error(
                    "Failed to build pricing product payload for SolidTariff %s",
                    saved_solid_tariff.external_id,
                    exc_info=True,
                )
            try:
                service.post_evse_pricing_update_for_tariff(saved_solid_tariff)
            except (ValueError, ValidationError):
                logger.error(
                    f"Failed to post EVSE pricing update for SolidTariff {saved_solid_tariff.external_id}",
                    exc_info=True,
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
            return (
                Decimal(str(per_minute_value)) * 60
                if per_minute_value is not None
                else None
            )
        except (ValueError, TypeError, InvalidOperation):
            return None

    def _set_missing_fields(self, validated_data):
        expected_keys = [
            "price_per_kwh",
            "price_per_min",
            "price_per_hr",
            "price_flat",
            "parking_price_per_min",
            "parking_price_per_hr",
            "vat_percentage",
            "parking_grace_period",
            "msp",
            "last_updated",
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

            self._set_tariff_alt_text(
                ocpi_tariff,
                per_kwh=per_kwh,
                per_hr=per_hr,
                flat=flat,
                parking_per_hr=parking_price_per_hr,
                parking_grace_minutes=grace_period,
                currency=currency,
                vat=vat,
            )

            solid_tariff = SolidTariff.objects.create(
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
            transaction.on_commit(ocpi_tariff.post_process_after_update_or_create)

        return solid_tariff

    def _get_ocpi_uid(self):
        # TODO: MSP specific ocpi tariffs requirement is not satisfied here.
        #  check https://github.com/solidroam/ocpiconnector/issues/253 for more details.
        return str(uuid.uuid4())

    def _create_ocpi_tariff(self, operator, currency, type: str = "") -> Tariff:
        random_ocpi_tariff_id = self._get_ocpi_uid()
        tariff = Tariff.objects.create(
            uid=random_ocpi_tariff_id,
            ocpi_master=operator,
            currency=currency,
            type=type,
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
            if price is not None:
                PriceComponent.objects.create(
                    tariff_element=tariff_element,
                    type=price_type,
                    price=price,
                    vat=vat,
                    step_size=1,
                )

    def _set_tariff_alt_text(
        self,
        tariff: Tariff,
        *,
        per_kwh: Optional[float],
        per_hr: Optional[float],
        flat: Optional[float],
        parking_per_hr: Optional[float],
        parking_grace_minutes: Optional[int],
        currency: str,
        vat: float,
    ) -> None:
        entries = TariffAltTextGenerator.build(
            per_kwh=per_kwh,
            per_hr=per_hr,
            flat=flat,
            parking_per_hr=parking_per_hr,
            parking_grace_minutes=parking_grace_minutes,
            currency=currency,
            vat=vat,
        )
        for language, text in entries:
            display_text, _ = DisplayText.objects.get_or_create(
                language=language, text=text
            )
            tariff.tariff_alt_text.add(display_text)

    def _send_updates_to_attached_connectors(self, old_solid_tariff, new_solid_tariff):
        if old_solid_tariff.ocpi_tariff is None:
            return
        with transaction.atomic():
            affected_locations = []
            for connector in old_solid_tariff.ocpi_tariff.connectors.all():
                connector.tariff_ids.remove(old_solid_tariff.ocpi_tariff)
                connector.tariff_ids.add(new_solid_tariff.ocpi_tariff)
                connector.save()
                affected_locations.append(connector.evse.location)
            for location in affected_locations:
                transaction.on_commit(location.post_process_after_update_or_create)

    def get_solid_tariff_external_id_by_ocpi_tariff_uid(self, ocpi_tariff_uid):
        try:
            solid_tariff = SolidTariff.objects.get(ocpi_tariff__uid=ocpi_tariff_uid)
            return solid_tariff.external_id
        except (Tariff.DoesNotExist, SolidTariff.DoesNotExist):
            return None


class CdrService:
    @classmethod
    def _get_charging_periods(cls, session: Session) -> list:
        if not session.chargingperiods.exists():
            logger.warning(
                f"No charging periods found for session {session.uid} to create CDR."
            )
            session.update_charging_periods(
                kwh=session.kwh, timestamp=session.start_date_time
            )

        charging_periods = ChargingPeriodSerializer(
            session.chargingperiods.all(), many=True
        ).data

        return charging_periods

    @classmethod
    def _get_cdr(cls, session_id: str) -> Optional["Cdr"]:
        from ocpi22.models.cdr import Cdr

        return Cdr.objects.filter(session_id=session_id).first()

    @classmethod
    def _get_cdr_tariffs(
        cls, charging_periods: list[dict], standard: str
    ) -> list[Tariff]:
        cdr_tariffs = []
        for charging_period in charging_periods:
            tariff_id = charging_period.get("tariff_id")
            if tariff_id:
                tariff = Tariff.objects.get_if_exists(
                    uid=tariff_id, archived=False, raise_exception=True
                )
                cdr_tariffs.append(tariff)
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
            total_cost_excl_vat=session.total_cost_excl_vat,
            total_cost_incl_vat=session.total_cost_incl_vat,
            total_energy=session.kwh,
            credentials=session.credentials,
            ocpi_master=session.ocpi_master,
            billed_to=session.billed_to,
            last_updated=datetime.now(pytz.utc),
        )

        cdr.tariffs.set(cdr_tariffs)

        event = cls._create_cdr_webhook_event(cdr)
        if event:
            transaction.on_commit(lambda: execute_webhook_event_task.delay(event.id))

        return cdr

    @classmethod
    def _create_cdr_webhook_event(cls, cdr: "Cdr") -> Optional[WebhookEvent]:
        from ocpi22.ocpi.serializers import CdrSerializer

        webhook = WebhookRepository.get_invoicing_webhook()
        if not webhook:
            return None

        payload = CdrSerializer(cdr).data
        try:
            with transaction.atomic():
                return WebhookEventService.create_event(
                    webhook=webhook,
                    event_type=WebhookEventType.CDR_CREATED,
                    payload=payload,
                )
        except Exception:
            logger.error(
                "Failed to create CDR webhook event for cdr %s",
                cdr.uid,
                exc_info=True,
            )
            return None

    @classmethod
    def get_or_create_cdr(cls, session: Session) -> Optional["Cdr"]:
        try:
            if not session.connector:
                logging.error(
                    f"Not creating a CDR from Session {session.uid} since no Connector is specified"
                )
                return None

            cdr = cls._get_cdr(session.uid)
            if cdr:
                return cdr

            if session.total_cost_excl_vat is None:
                logger.error(f"Session {session} has no total cost")
                return None
            if not session.end_date_time:
                session.end_date_time = datetime.now(pytz.utc)

            cdr = cls._create_cdr(session)

            if settings.ENABLE_HUBJECT:
                if session.route_through_oicp:
                    from integrations.hubject.services import HubjectService

                    HubjectService.post_eroaming_charge_detail_record(
                        cdr.ocpi_master.party_str(), cdr
                    )

                    return cdr

            cdr.send_updates()

            return cdr
        except (RestFrameworkValidationError, ObjectDoesNotExist) as e:
            logger.error(e)
            return None
