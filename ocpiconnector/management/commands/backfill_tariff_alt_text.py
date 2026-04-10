from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import OuterRef, Subquery

from ocpi22.cpo.services import TariffAltTextGenerator
from ocpi22.models.displaytext import DisplayText
from ocpi22.models.tariff import SolidTariff


class Command(BaseCommand):
    help = "Backfill tariff_alt_text for all active SolidTariff OCPI tariffs that have none."

    def handle(self, *args, **options) -> None:
        latest_id_per_external_id = (
            SolidTariff.objects.filter(
                external_id=OuterRef("external_id"), msp__isnull=True
            )
            .order_by("-created_at")
            .values("id")[:1]
        )
        candidates = (
            SolidTariff.objects.filter(
                msp__isnull=True, id__in=Subquery(latest_id_per_external_id)
            )
            .filter(
                ocpi_tariff__isnull=False, ocpi_tariff__tariff_alt_text__isnull=True
            )
            .select_related("ocpi_tariff")
        )

        total = candidates.count()
        self.stdout.write(f"Found {total} SolidTariff(s) without tariff_alt_text.")

        skipped = 0
        updated = 0

        for solid_tariff in candidates:
            per_hr = self._effective_per_hr(solid_tariff)
            parking_per_hr = self._effective_parking_per_hr(solid_tariff)
            per_kwh = (
                float(solid_tariff.price_per_kwh)
                if solid_tariff.price_per_kwh is not None
                else None
            )
            flat = (
                float(solid_tariff.price_flat)
                if solid_tariff.price_flat is not None
                else None
            )

            if not TariffAltTextGenerator.has_price_components(
                per_kwh, per_hr, flat, parking_per_hr
            ):
                self.stdout.write(
                    f"  SKIP  SolidTariff {solid_tariff.pk} (external_id={solid_tariff.external_id}): no price components"
                )
                skipped += 1
                continue

            entries = TariffAltTextGenerator.build(
                per_kwh=per_kwh,
                per_hr=per_hr,
                flat=flat,
                parking_per_hr=parking_per_hr,
                parking_grace_minutes=solid_tariff.parking_grace_period,
                currency=solid_tariff.currency,
            )

            with transaction.atomic():
                tariff = solid_tariff.ocpi_tariff
                for language, text in entries:
                    display_text = DisplayText.objects.create(
                        language=language, text=text
                    )
                    tariff.tariff_alt_text.add(display_text)
                tariff.post_process_after_update_or_create()

            self.stdout.write(
                f"  OK    SolidTariff {solid_tariff.pk} (external_id={solid_tariff.external_id}): added {len(entries)} language(s)"
            )
            updated += 1

        self.stdout.write(f"Done. Updated: {updated}, skipped: {skipped}.")

    def _effective_per_hr(self, solid_tariff: SolidTariff) -> float | None:
        if solid_tariff.price_per_hr is not None:
            return float(solid_tariff.price_per_hr)
        if solid_tariff.price_per_min is not None:
            return float(solid_tariff.price_per_min) * 60
        return None

    def _effective_parking_per_hr(self, solid_tariff: SolidTariff) -> float | None:
        if solid_tariff.parking_price_per_hr is not None:
            return float(solid_tariff.parking_price_per_hr)
        if solid_tariff.parking_price_per_min is not None:
            return float(solid_tariff.parking_price_per_min) * 60
        return None
