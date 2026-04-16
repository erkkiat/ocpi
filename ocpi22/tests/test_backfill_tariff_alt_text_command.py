import datetime
import zoneinfo
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.test import override_settings

from ocpi22.models.tariff import PriceComponent, SolidTariff, Tariff
from ocpi22.tests.factories import ConnectorFactory, SolidTariffFactory


def _solid_tariff(operator, external_id, **pricing):
    defaults = dict(
        price_per_kwh=None,
        price_per_min=None,
        price_per_hr=None,
        price_flat=None,
        parking_price_per_min=None,
        parking_price_per_hr=None,
        parking_grace_period=None,
        vat_percentage=None,
        msp=None,
        operator=operator,
        external_id=external_id,
        currency="EUR",
    )
    defaults.update(pricing)
    return SolidTariffFactory(**defaults)


@pytest.mark.django_db
def test_backfill_creates_new_ocpi_tariff_for_solid_tariff(operator_fi_cpo):
    solid_tariff = _solid_tariff(operator_fi_cpo, "T-1", price_per_kwh=0.45)
    original_ocpi_tariff_pk = solid_tariff.ocpi_tariff.pk

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text")

    solid_tariff.refresh_from_db()
    assert solid_tariff.ocpi_tariff.pk != original_ocpi_tariff_pk


@pytest.mark.django_db
def test_backfill_new_ocpi_tariff_has_alt_text(operator_fi_cpo):
    solid_tariff = _solid_tariff(
        operator_fi_cpo, "T-2", price_per_kwh=0.45, price_per_hr=6.0
    )

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text")

    solid_tariff.refresh_from_db()
    alt_texts = {
        dt.language: dt.text for dt in solid_tariff.ocpi_tariff.tariff_alt_text.all()
    }
    assert set(alt_texts.keys()) == {"en", "fr", "nl"}
    assert alt_texts["en"] == "€0.45/kWh + €6.00/h charging"


@pytest.mark.django_db
def test_backfill_new_ocpi_tariff_has_price_components(operator_fi_cpo):
    solid_tariff = _solid_tariff(
        operator_fi_cpo, "T-3", price_per_kwh=0.45, price_per_hr=6.0
    )

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text")

    solid_tariff.refresh_from_db()
    types = set(
        PriceComponent.objects.filter(
            tariff_element__tariff=solid_tariff.ocpi_tariff
        ).values_list("type", flat=True)
    )
    assert types == {"ENERGY", "TIME"}


@pytest.mark.django_db
def test_backfill_old_ocpi_tariff_is_not_modified(operator_fi_cpo):
    solid_tariff = _solid_tariff(operator_fi_cpo, "T-4", price_per_kwh=0.45)
    old_ocpi_tariff_pk = solid_tariff.ocpi_tariff.pk

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text")

    old_tariff = Tariff.objects.get(pk=old_ocpi_tariff_pk)
    assert old_tariff.tariff_alt_text.count() == 0


@pytest.mark.django_db
def test_backfill_skips_solid_tariff_with_no_price_components(operator_fi_cpo):
    _solid_tariff(operator_fi_cpo, "T-5")

    with patch.object(Tariff, "post_process_after_update_or_create") as mock_push:
        call_command("backfill_tariff_alt_text")

    mock_push.assert_not_called()


@pytest.mark.django_db
def test_backfill_only_processes_latest_solid_tariff_per_external_id(operator_fi_cpo):
    t1 = datetime.datetime(2024, 1, 1, tzinfo=zoneinfo.ZoneInfo("UTC"))
    t2 = datetime.datetime(2024, 6, 1, tzinfo=zoneinfo.ZoneInfo("UTC"))

    old = _solid_tariff(operator_fi_cpo, "T-6", price_per_kwh=0.30)
    SolidTariff.objects.filter(pk=old.pk).update(created_at=t1)

    latest = _solid_tariff(operator_fi_cpo, "T-6", price_per_kwh=0.45)
    SolidTariff.objects.filter(pk=latest.pk).update(created_at=t2)

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text")

    latest.refresh_from_db()
    old.refresh_from_db()
    assert latest.ocpi_tariff.tariff_alt_text.count() == 3
    assert old.ocpi_tariff.tariff_alt_text.count() == 0


@pytest.mark.django_db
def test_backfill_converts_price_per_min_to_hourly(operator_fi_cpo):
    solid_tariff = _solid_tariff(operator_fi_cpo, "T-7", price_per_min=0.1)

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text")

    solid_tariff.refresh_from_db()
    alt_texts = {
        dt.language: dt.text for dt in solid_tariff.ocpi_tariff.tariff_alt_text.all()
    }
    assert alt_texts["en"] == "€6.00/h charging"


@pytest.mark.django_db
def test_backfill_converts_parking_price_per_min_to_hourly(operator_fi_cpo):
    solid_tariff = _solid_tariff(
        operator_fi_cpo, "T-8", price_per_kwh=0.45, parking_price_per_min=0.05
    )

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text")

    solid_tariff.refresh_from_db()
    alt_texts = {
        dt.language: dt.text for dt in solid_tariff.ocpi_tariff.tariff_alt_text.all()
    }
    assert alt_texts["en"] == "€0.45/kWh + €3.00/h parking"


@pytest.mark.django_db
def test_backfill_swaps_connector_tariff_references(operator_fi_cpo):
    solid_tariff = _solid_tariff(operator_fi_cpo, "T-9", price_per_kwh=0.45)
    old_ocpi_tariff = solid_tariff.ocpi_tariff
    connector = ConnectorFactory(tariff_ids=[old_ocpi_tariff])

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text")

    solid_tariff.refresh_from_db()
    connector.refresh_from_db()
    assert list(connector.tariff_ids.all()) == [solid_tariff.ocpi_tariff]
    assert old_ocpi_tariff not in connector.tariff_ids.all()


@pytest.mark.django_db
def test_backfill_triggers_location_post_process_for_attached_connector(
    operator_fi_cpo,
):
    from ocpi22.models.location import Location

    solid_tariff = _solid_tariff(operator_fi_cpo, "T-9b", price_per_kwh=0.45)
    connector = ConnectorFactory(tariff_ids=[solid_tariff.ocpi_tariff])

    with (
        patch.object(Tariff, "post_process_after_update_or_create"),
        patch.object(
            Location, "post_process_after_update_or_create"
        ) as mock_location_push,
    ):
        call_command("backfill_tariff_alt_text")

    mock_location_push.assert_called_once()
    solid_tariff.refresh_from_db()
    assert solid_tariff.ocpi_tariff in connector.tariff_ids.all()


@pytest.mark.django_db
def test_backfill_calls_post_process_on_new_ocpi_tariff(operator_fi_cpo):
    _solid_tariff(operator_fi_cpo, "T-10", price_per_kwh=0.45)

    with patch.object(Tariff, "post_process_after_update_or_create") as mock_push:
        call_command("backfill_tariff_alt_text")

    mock_push.assert_called_once()


@pytest.mark.django_db
def test_backfill_post_process_called_before_connector_swap(operator_fi_cpo):
    from ocpi22.management.commands.backfill_tariff_alt_text import Command

    _solid_tariff(operator_fi_cpo, "T-11", price_per_kwh=0.45)

    call_order = []

    def record_post_process(*args, **kwargs):
        call_order.append("post_process")

    def record_swap(self, old, new):
        call_order.append("swap")

    with (
        patch.object(
            Tariff, "post_process_after_update_or_create", record_post_process
        ),
        patch.object(Command, "_swap_connector_tariff_references", record_swap),
    ):
        call_command("backfill_tariff_alt_text")

    assert call_order == ["post_process", "swap"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "external_ids,expected_count",
    [
        pytest.param(["T-12"], 1, id="retry_one"),
        pytest.param(["T-12", "T-13"], 2, id="retry_two"),
    ],
)
def test_backfill_external_ids_filter_only_processes_specified(
    operator_fi_cpo, external_ids, expected_count
):
    _solid_tariff(operator_fi_cpo, "T-12", price_per_kwh=0.45)
    _solid_tariff(operator_fi_cpo, "T-13", price_per_kwh=0.50)
    _solid_tariff(operator_fi_cpo, "T-14", price_per_kwh=0.55)

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text", external_ids=external_ids)

    for external_id in external_ids:
        solid_tariff = SolidTariff.objects.filter(external_id=external_id).latest(
            "created_at"
        )
        assert solid_tariff.ocpi_tariff.tariff_alt_text.count() == 3

    unprocessed = SolidTariff.objects.filter(external_id="T-14").latest("created_at")
    assert unprocessed.ocpi_tariff.tariff_alt_text.count() == 0


@pytest.mark.django_db
def test_backfill_continues_after_failure_and_processes_remaining(operator_fi_cpo):
    _solid_tariff(operator_fi_cpo, "T-15", price_per_kwh=0.45)
    second = _solid_tariff(operator_fi_cpo, "T-16", price_per_kwh=0.50)
    original_second_pk = second.ocpi_tariff.pk

    call_count = 0

    def fail_first(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("simulated failure")

    with patch.object(Tariff, "post_process_after_update_or_create", fail_first):
        call_command("backfill_tariff_alt_text")

    second.refresh_from_db()
    assert second.ocpi_tariff.pk != original_second_pk
    assert second.ocpi_tariff.tariff_alt_text.count() == 3


@pytest.mark.django_db
def test_backfill_processes_all_distinct_tariffs(operator_fi_cpo):
    _solid_tariff(operator_fi_cpo, "T-17", price_per_kwh=0.45)
    _solid_tariff(operator_fi_cpo, "T-18", price_per_kwh=0.50)
    _solid_tariff(operator_fi_cpo, "T-19", price_per_kwh=0.55)

    with patch.object(Tariff, "post_process_after_update_or_create"):
        call_command("backfill_tariff_alt_text")

    for external_id in ["T-17", "T-18", "T-19"]:
        solid_tariff = SolidTariff.objects.filter(external_id=external_id).latest(
            "created_at"
        )
        assert solid_tariff.ocpi_tariff.tariff_alt_text.count() == 3


@pytest.mark.django_db
@override_settings(ENABLE_HUBJECT=True)
def test_backfill_syncs_hubject_when_enabled(operator_fi_cpo):
    _solid_tariff(operator_fi_cpo, "T-20", price_per_kwh=0.45)

    with (
        patch.object(Tariff, "post_process_after_update_or_create"),
        patch(
            "integrations.hubject.services.HubjectService.get_pricing_product_insert_payload",
            return_value={},
        ),
        patch(
            "integrations.hubject.services.HubjectService.post_pricing_products"
        ) as mock_post,
        patch(
            "integrations.hubject.services.HubjectService.post_evse_pricing_update_for_tariff"
        ) as mock_evse,
    ):
        call_command("backfill_tariff_alt_text")

    mock_post.assert_called_once()
    mock_evse.assert_called_once()


@pytest.mark.django_db
@override_settings(ENABLE_HUBJECT=False)
def test_backfill_skips_hubject_when_disabled(operator_fi_cpo):
    _solid_tariff(operator_fi_cpo, "T-21", price_per_kwh=0.45)

    with (
        patch.object(Tariff, "post_process_after_update_or_create"),
        patch(
            "integrations.hubject.services.HubjectService.post_pricing_products"
        ) as mock_post,
    ):
        call_command("backfill_tariff_alt_text")

    mock_post.assert_not_called()
