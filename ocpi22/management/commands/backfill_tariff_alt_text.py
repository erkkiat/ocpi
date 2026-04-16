import logging
import time
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import OuterRef, Subquery

from ocpi22.cpo.services import SolidTariffService, TariffAltTextGenerator
from ocpi22.models.tariff import SolidTariff

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Backfill alt text by creating a new OCPI tariff for the latest SolidTariff per external_id."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--delay",
            type=float,
            default=0.2,
            help="Seconds to wait between each tariff's HTTP calls (default: 0.2, i.e. 5/second).",
        )
        parser.add_argument(
            "--external-ids",
            nargs="+",
            dest="external_ids",
            default=None,
            metavar="EXTERNAL_ID",
            help="Only process solid tariffs with these external IDs. Useful for retrying failed ones.",
        )

    def handle(self, *args, **options) -> None:
        service = SolidTariffService()
        delay = options["delay"]
        external_ids = options["external_ids"]
        solid_tariffs = self._get_distinct_latest_solid_tariffs(external_ids)
        total = solid_tariffs.count()
        self.stdout.write(f"Found {total} distinct solid tariff(s) to process.")

        processed = 0
        skipped = 0
        failed_ids: list[str] = []

        for index, solid_tariff in enumerate(
            solid_tariffs.iterator(chunk_size=100), start=1
        ):
            try:
                did_backfill = self._backfill(
                    service, solid_tariff, delay, index, total
                )
                if did_backfill:
                    processed += 1
                else:
                    skipped += 1
            except Exception:
                failed_ids.append(solid_tariff.external_id)
                logger.error(
                    "Failed to backfill SolidTariff %s",
                    solid_tariff.external_id,
                    exc_info=True,
                )
                self.stdout.write(
                    self.style.ERROR(
                        f"[{index}/{total}] {solid_tariff.external_id} — failed (see logs)"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Processed: {processed} | Skipped: {skipped} | Failed: {len(failed_ids)} | Total: {total}"
            )
        )
        if failed_ids:
            self.stdout.write(self.style.ERROR("\nFailed external IDs:"))
            self.stdout.write(self.style.ERROR(" ".join(failed_ids)))
            self.stdout.write(
                self.style.ERROR(
                    "\nRetry with: python manage.py backfill_tariff_alt_text --external-ids "
                    + " ".join(failed_ids)
                )
            )

    def _get_distinct_latest_solid_tariffs(self, external_ids: Optional[list[str]]):
        latest_pk_subquery = Subquery(
            SolidTariff.objects.filter(external_id=OuterRef("external_id"))
            .order_by("-created_at")
            .values("pk")[:1]
        )
        queryset = SolidTariff.objects.filter(pk=latest_pk_subquery).select_related(
            "ocpi_tariff", "operator"
        )
        if external_ids:
            queryset = queryset.filter(external_id__in=external_ids)
        return queryset

    def _backfill(
        self,
        service: SolidTariffService,
        solid_tariff: SolidTariff,
        delay: float,
        index: int,
        total: int,
    ) -> bool:
        prefix = f"[{index}/{total}] {solid_tariff.external_id}"

        per_kwh = self._to_float(solid_tariff.price_per_kwh)
        per_hr = (
            self._to_float(solid_tariff.price_per_hr)
            if solid_tariff.price_per_hr is not None
            else self._to_hourly(solid_tariff.price_per_min)
        )
        flat = self._to_float(solid_tariff.price_flat)
        parking_per_hr = (
            self._to_float(solid_tariff.parking_price_per_hr)
            if solid_tariff.parking_price_per_hr is not None
            else self._to_hourly(solid_tariff.parking_price_per_min)
        )

        if not TariffAltTextGenerator.has_price_components(
            per_kwh, per_hr, flat, parking_per_hr
        ):
            self.stdout.write(
                self.style.WARNING(f"{prefix} — skipped (no price components)")
            )
            return False

        old_ocpi_tariff = solid_tariff.ocpi_tariff

        with transaction.atomic():
            new_ocpi_tariff = service._create_ocpi_tariff(
                solid_tariff.operator,
                solid_tariff.currency,
                type="AD_HOC_PAYMENT",
            )
            service._create_price_components(
                new_ocpi_tariff,
                per_kwh,
                per_hr,
                flat,
                parking_per_hr,
                solid_tariff.vat_percentage,
            )
            service._set_tariff_alt_text(
                new_ocpi_tariff,
                per_kwh=per_kwh,
                per_hr=per_hr,
                flat=flat,
                parking_per_hr=parking_per_hr,
                parking_grace_minutes=solid_tariff.parking_grace_period,
                currency=solid_tariff.currency,
            )
            SolidTariff.objects.filter(pk=solid_tariff.pk).update(
                ocpi_tariff=new_ocpi_tariff
            )

        new_ocpi_tariff.post_process_after_update_or_create()
        self._swap_connector_tariff_references(old_ocpi_tariff, new_ocpi_tariff)

        solid_tariff.refresh_from_db()
        self._sync_hubject(solid_tariff)

        time.sleep(delay)
        self.stdout.write(
            self.style.SUCCESS(f"{prefix} — backfilled (uid={new_ocpi_tariff.uid})")
        )
        return True

    @staticmethod
    def _swap_connector_tariff_references(old_ocpi_tariff, new_ocpi_tariff) -> None:
        for connector in old_ocpi_tariff.connectors.all():
            connector.tariff_ids.remove(old_ocpi_tariff)
            connector.tariff_ids.add(new_ocpi_tariff)
            connector.save()
            connector.evse.location.post_process_after_update_or_create()

    def _sync_hubject(self, solid_tariff: SolidTariff) -> None:
        if not settings.ENABLE_HUBJECT:
            return
        from integrations.hubject.services import HubjectService

        hubject_service = HubjectService()
        try:
            pricing_payload = hubject_service.get_pricing_product_insert_payload(
                solid_tariff
            )
            hubject_service.post_pricing_products(pricing_payload)
        except (ValueError, ValidationError):
            logger.error(
                "Failed to build pricing product payload for SolidTariff %s",
                solid_tariff.external_id,
                exc_info=True,
            )
        try:
            hubject_service.post_evse_pricing_update_for_tariff(solid_tariff)
        except (ValueError, ValidationError):
            logger.error(
                "Failed to post EVSE pricing update for SolidTariff %s",
                solid_tariff.external_id,
                exc_info=True,
            )

    @staticmethod
    def _to_float(value: Optional[Decimal]) -> Optional[float]:
        if value is None:
            return None
        return float(value)

    @staticmethod
    def _to_hourly(per_minute: Optional[Decimal]) -> Optional[float]:
        if per_minute is None:
            return None
        try:
            return float(Decimal(str(per_minute)) * 60)
        except (ValueError, TypeError, InvalidOperation):
            return None
