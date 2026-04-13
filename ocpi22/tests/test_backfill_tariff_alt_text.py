import datetime
import zoneinfo
from unittest.mock import patch

import pytest
from django.core.management import call_command

from ocpi22.models.tariff import SolidTariff, Tariff
from ocpi22.tests.factories import SolidTariffFactory, TariffFactory


def _solid_tariff(operator, external_id, **pricing):
    defaults = dict(
        price_per_kwh=None,
        price_per_min=None,
        price_per_hr=None,
        price_flat=None,
        parking_price_per_min=None,
        parking_price_per_hr=None,
        parking_grace_period=None,
        msp=None,
        operator=operator,
        external_id=external_id,
        currency="EUR",
    )
    defaults.update(pricing)
    return SolidTariffFactory(**defaults)


@pytest.mark.django_db
def test_backfill_tariff_alt_text_adds_alt_text_for_latest_solid_tariff(
    operator_fi_cpo,
):
    solid_tariff = _solid_tariff(
        operator_fi_cpo, "BACK-1", price_per_kwh=0.45, price_per_hr=6.0
    )

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text")

    alt_texts = {
        dt.language: dt.text for dt in solid_tariff.ocpi_tariff.tariff_alt_text.all()
    }
    assert set(alt_texts.keys()) == {"en", "fr", "nl"}
    assert alt_texts["en"] == "€0.45/kWh + €6.00/h charging"
    assert alt_texts["fr"] == "0,45€/kWh + 6,00€/h recharge"
    assert alt_texts["nl"] == "€0,45/kWh + €6,00/u opladen"


@pytest.mark.django_db
def test_backfill_tariff_alt_text_triggers_ocpi_push(operator_fi_cpo):
    _solid_tariff(operator_fi_cpo, "BACK-2", price_per_kwh=0.45)

    with patch.object(Tariff, "post_process_after_update_or_create") as mock_push:
        call_command("backfill_tariff_alt_text")

    mock_push.assert_called_once()


@pytest.mark.django_db
def test_backfill_tariff_alt_text_skips_tariff_already_having_alt_text(operator_fi_cpo):
    from ocpi22.models.displaytext import DisplayText

    solid_tariff = _solid_tariff(operator_fi_cpo, "BACK-3", price_per_kwh=0.45)
    existing = DisplayText.objects.create(language="en", text="existing")
    solid_tariff.ocpi_tariff.tariff_alt_text.add(existing)

    with patch.object(Tariff, "post_process_after_update_or_create") as mock_push:
        call_command("backfill_tariff_alt_text")

    mock_push.assert_not_called()
    assert solid_tariff.ocpi_tariff.tariff_alt_text.count() == 1


@pytest.mark.django_db
def test_backfill_tariff_alt_text_skips_solid_tariff_with_no_price_components(
    operator_fi_cpo,
):
    _solid_tariff(operator_fi_cpo, "BACK-4")

    with patch.object(Tariff, "post_process_after_update_or_create") as mock_push:
        call_command("backfill_tariff_alt_text")

    mock_push.assert_not_called()


@pytest.mark.django_db
def test_backfill_tariff_alt_text_only_processes_latest_solid_tariff_per_external_id(
    operator_fi_cpo,
):
    t1 = datetime.datetime(2024, 1, 1, tzinfo=zoneinfo.ZoneInfo("UTC"))
    t2 = datetime.datetime(2024, 6, 1, tzinfo=zoneinfo.ZoneInfo("UTC"))

    old = _solid_tariff(operator_fi_cpo, "BACK-5", price_per_kwh=0.30)
    SolidTariff.objects.filter(pk=old.pk).update(created_at=t1)

    latest = _solid_tariff(operator_fi_cpo, "BACK-5", price_per_kwh=0.45)
    SolidTariff.objects.filter(pk=latest.pk).update(created_at=t2)

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text")

    assert old.ocpi_tariff.tariff_alt_text.count() == 0
    assert latest.ocpi_tariff.tariff_alt_text.count() == 3


@pytest.mark.django_db
def test_backfill_tariff_alt_text_converts_per_min_to_hourly(operator_fi_cpo):
    solid_tariff = _solid_tariff(operator_fi_cpo, "BACK-6", price_per_min=0.1)

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text")

    alt_texts = {
        dt.language: dt.text for dt in solid_tariff.ocpi_tariff.tariff_alt_text.all()
    }
    assert alt_texts["en"] == "€6.00/h charging"


@pytest.mark.django_db
def test_backfill_tariff_alt_text_converts_parking_per_min_to_hourly(operator_fi_cpo):
    solid_tariff = _solid_tariff(
        operator_fi_cpo, "BACK-7", price_per_kwh=0.45, parking_price_per_min=0.05
    )

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text")

    alt_texts = {
        dt.language: dt.text for dt in solid_tariff.ocpi_tariff.tariff_alt_text.all()
    }
    assert alt_texts["en"] == "€0.45/kWh + €3.00/h parking"


@pytest.mark.django_db
def test_backfill_tariff_alt_text_is_idempotent(operator_fi_cpo):
    solid_tariff = _solid_tariff(operator_fi_cpo, "BACK-8", price_per_kwh=0.45)

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text")
        call_command("backfill_tariff_alt_text")

    assert solid_tariff.ocpi_tariff.tariff_alt_text.count() == 3


@pytest.mark.django_db
def test_backfill_solid_tariff_ocpi_tariff_fk_is_intact_after_backfill(operator_fi_cpo):
    solid_tariff = _solid_tariff(operator_fi_cpo, "BACK-9", price_per_kwh=0.45)
    original_ocpi_tariff_pk = solid_tariff.ocpi_tariff.pk

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text")

    solid_tariff.refresh_from_db()
    assert solid_tariff.ocpi_tariff.pk == original_ocpi_tariff_pk


@pytest.mark.django_db
def test_backfill_alt_text_display_texts_are_linked_to_correct_ocpi_tariff(
    operator_fi_cpo,
):
    solid_tariff = _solid_tariff(operator_fi_cpo, "BACK-10", price_per_kwh=0.45)
    other = _solid_tariff(operator_fi_cpo, "BACK-11", price_per_kwh=0.99)

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text")

    solid_tariff_texts = set(
        solid_tariff.ocpi_tariff.tariff_alt_text.values_list("text", flat=True)
    )
    other_texts = set(other.ocpi_tariff.tariff_alt_text.values_list("text", flat=True))

    assert all("0.45" in t or "0,45" in t for t in solid_tariff_texts)
    assert all("0.99" in t or "0,99" in t for t in other_texts)
    assert solid_tariff_texts.isdisjoint(other_texts)


@pytest.mark.django_db
def test_backfill_writes_alt_text_to_ocpi_tariff_linked_via_solid_tariff_fk(
    operator_fi_cpo,
):
    solid_tariff = _solid_tariff(operator_fi_cpo, "BACK-REL", price_per_kwh=0.45)
    unrelated_tariff = TariffFactory(ocpi_master=operator_fi_cpo)

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text")

    assert solid_tariff.ocpi_tariff.tariff_alt_text.count() == 3
    assert unrelated_tariff.tariff_alt_text.count() == 0


@pytest.mark.django_db
def test_backfill_old_ocpi_tariff_is_not_touched_when_new_version_exists(
    operator_fi_cpo,
):
    t1 = datetime.datetime(2024, 1, 1, tzinfo=zoneinfo.ZoneInfo("UTC"))
    t2 = datetime.datetime(2024, 6, 1, tzinfo=zoneinfo.ZoneInfo("UTC"))

    old = _solid_tariff(operator_fi_cpo, "BACK-12", price_per_kwh=0.30)
    SolidTariff.objects.filter(pk=old.pk).update(created_at=t1)
    old_ocpi_tariff_pk = old.ocpi_tariff.pk

    latest = _solid_tariff(operator_fi_cpo, "BACK-12", price_per_kwh=0.45)
    SolidTariff.objects.filter(pk=latest.pk).update(created_at=t2)

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text")

    old_tariff = Tariff.objects.get(pk=old_ocpi_tariff_pk)
    assert old_tariff.tariff_alt_text.count() == 0
    assert latest.ocpi_tariff.tariff_alt_text.count() == 3
    assert old.ocpi_tariff.pk != latest.ocpi_tariff.pk
