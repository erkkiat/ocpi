import pytest

from ocpi22.cpo.services import SolidTariffService, TariffAltTextGenerator


def _build(**overrides):
    defaults = dict(
        per_kwh=None,
        per_hr=None,
        flat=None,
        parking_per_hr=None,
        parking_grace_minutes=None,
        currency="EUR",
        vat=0.0,
    )
    defaults.update(overrides)
    return dict(TariffAltTextGenerator.build(**defaults))


@pytest.mark.parametrize(
    "kwargs, expected_en, expected_fr, expected_nl",
    [
        pytest.param(
            {"per_kwh": 0.45},
            "€0.45/kWh",
            "0,45€/kWh",
            "€0,45/kWh",
            id="energy_only",
        ),
        pytest.param(
            {"per_kwh": 0.45, "per_hr": 6.0},
            "€0.45/kWh + €6.00/h charging",
            "0,45€/kWh + 6,00€/h recharge",
            "€0,45/kWh + €6,00/u opladen",
            id="energy_plus_time",
        ),
        pytest.param(
            {"per_kwh": 0.50, "flat": 2.0},
            "€0.50/kWh + €2.00 starting fee",
            "0,50€/kWh + 2,00€ frais de démarrage",
            "€0,50/kWh + €2,00 startkost",
            id="energy_plus_flat",
        ),
        pytest.param(
            {"per_kwh": 0.38, "parking_per_hr": 3.0},
            "€0.38/kWh + €3.00/h parking",
            "0,38€/kWh + 3,00€/h stationnement",
            "€0,38/kWh + €3,00/u parkeren",
            id="energy_plus_parking_no_grace",
        ),
        pytest.param(
            {"per_kwh": 0.38, "parking_per_hr": 3.0, "parking_grace_minutes": 15},
            "€0.38/kWh + €3.00/h parking after 15min",
            "0,38€/kWh + 3,00€/h stationnement après 15min",
            "€0,38/kWh + €3,00/u parkeren na 15min",
            id="energy_plus_parking_with_grace",
        ),
        pytest.param(
            {
                "per_kwh": 0.50,
                "per_hr": 6.0,
                "flat": 1.0,
                "parking_per_hr": 3.0,
                "parking_grace_minutes": 15,
            },
            "€0.50/kWh + €6.00/h charging + €1.00 starting fee + €3.00/h parking after 15min",
            "0,50€/kWh + 6,00€/h recharge + 1,00€ frais de démarrage + 3,00€/h stationnement après 15min",
            "€0,50/kWh + €6,00/u opladen + €1,00 startkost + €3,00/u parkeren na 15min",
            id="all_components_with_grace",
        ),
        pytest.param(
            {"flat": 2.0},
            "€2.00 starting fee",
            "2,00€ frais de démarrage",
            "€2,00 startkost",
            id="flat_only",
        ),
        pytest.param(
            {"per_hr": 0.05},
            "€0.05/h charging",
            "0,05€/h recharge",
            "€0,05/u opladen",
            id="time_only",
        ),
        pytest.param(
            {"per_kwh": 0.0},
            "€0.00/kWh",
            "0,00€/kWh",
            "€0,00/kWh",
            id="zero_energy_is_displayed_as_free",
        ),
        pytest.param(
            {"per_kwh": 0.45, "flat": 0.0, "per_hr": 0.0, "parking_per_hr": 0.0},
            "€0.45/kWh + €0.00/h charging + €0.00 starting fee + €0.00/h parking",
            "0,45€/kWh + 0,00€/h recharge + 0,00€ frais de démarrage + 0,00€/h stationnement",
            "€0,45/kWh + €0,00/u opladen + €0,00 startkost + €0,00/u parkeren",
            id="zero_additive_components_are_displayed",
        ),
    ],
)
def test_build_tariff_alt_text(kwargs, expected_en, expected_fr, expected_nl):
    result = _build(**kwargs)
    assert result["en"] == expected_en
    assert result["fr"] == expected_fr
    assert result["nl"] == expected_nl


def test_build_tariff_alt_text_raises_when_no_components():
    with pytest.raises(ValueError, match="price component"):
        TariffAltTextGenerator.build(
            per_kwh=None,
            per_hr=None,
            flat=None,
            parking_per_hr=None,
            parking_grace_minutes=None,
            currency="EUR",
            vat=0.0,
        )


def test_build_tariff_alt_text_zero_additives_are_displayed():
    result = dict(
        TariffAltTextGenerator.build(
            per_kwh=None,
            per_hr=0.0,
            flat=None,
            parking_per_hr=None,
            parking_grace_minutes=None,
            currency="EUR",
            vat=0.0,
        )
    )
    assert result["en"] == "€0.00/h charging"


def test_build_tariff_alt_text_grace_zero_treated_as_no_grace():
    result = _build(parking_per_hr=3.0, parking_grace_minutes=0)
    assert result["en"] == "€3.00/h parking"


def test_build_tariff_alt_text_non_eur_currency_uses_iso_code():
    result = _build(per_kwh=0.45, currency="GBP")
    assert result["en"] == "GBP 0.45/kWh"
    assert result["fr"] == "GBP 0,45/kWh"
    assert result["nl"] == "GBP 0,45/kWh"


@pytest.mark.django_db
def test_create_solid_tariff_populates_ocpi_tariff_alt_text(operator_fi_cpo):
    service = SolidTariffService()
    validated_data = {
        "external_id": "ALT-TEXT-1",
        "currency": "EUR",
        "price_per_kwh": 0.45,
        "price_per_hr": 6.0,
        "parking_price_per_hr": 3.0,
        "parking_grace_period": 15,
        "vat_percentage": 0.0,
        "ocpi_master": operator_fi_cpo,
        "msp": None,
    }

    solid_tariff = service.create(validated_data)

    alt_texts = {
        display_text.language: display_text.text
        for display_text in solid_tariff.ocpi_tariff.tariff_alt_text.all()
    }
    assert set(alt_texts.keys()) == {"en", "fr", "nl"}
    assert alt_texts["en"] == (
        "€0.45/kWh + €6.00/h charging + €3.00/h parking after 15min"
    )
    assert alt_texts["fr"] == (
        "0,45€/kWh + 6,00€/h recharge + 3,00€/h stationnement après 15min"
    )
    assert alt_texts["nl"] == (
        "€0,45/kWh + €6,00/u opladen + €3,00/u parkeren na 15min"
    )


@pytest.mark.django_db
def test_updating_solid_tariff_creates_fresh_alt_text_on_new_ocpi_tariff(
    operator_fi_cpo,
):
    service = SolidTariffService()
    base = {
        "external_id": "ALT-TEXT-2",
        "currency": "EUR",
        "price_per_kwh": 0.45,
        "vat_percentage": 0.0,
        "ocpi_master": operator_fi_cpo,
        "msp": None,
    }
    first = service.create(dict(base))
    updated = dict(base)
    updated["price_per_kwh"] = 0.99
    second = service.create(updated)

    assert first.ocpi_tariff.pk != second.ocpi_tariff.pk

    first_texts = {
        display_text.language: display_text.text
        for display_text in first.ocpi_tariff.tariff_alt_text.all()
    }
    second_texts = {
        display_text.language: display_text.text
        for display_text in second.ocpi_tariff.tariff_alt_text.all()
    }
    assert first_texts["en"] == "€0.45/kWh"
    assert second_texts["en"] == "€0.99/kWh"


@pytest.mark.django_db
def test_create_solid_tariff_with_no_price_components_is_rejected(
    operator_fi_cpo,
):
    from django.core.exceptions import ValidationError

    service = SolidTariffService()
    validated_data = {
        "external_id": "ALT-TEXT-3",
        "currency": "EUR",
        "ocpi_master": operator_fi_cpo,
        "msp": None,
    }

    with pytest.raises(ValidationError, match="price"):
        service.create(validated_data)


@pytest.mark.parametrize(
    "kwargs, expected_en, expected_fr, expected_nl",
    [
        pytest.param(
            {"per_kwh": 0.45, "vat": 21.0},
            "€0.54/kWh",
            "0,54€/kWh",
            "€0,54/kWh",
            id="energy_with_21pct_vat",
        ),
        pytest.param(
            {"per_kwh": 0.45, "per_hr": 6.0, "vat": 10.0},
            "€0.50/kWh + €6.60/h charging",
            "0,50€/kWh + 6,60€/h recharge",
            "€0,50/kWh + €6,60/u opladen",
            id="energy_and_time_with_10pct_vat",
        ),
        pytest.param(
            {"flat": 2.0, "vat": 20.0},
            "€2.40 starting fee",
            "2,40€ frais de démarrage",
            "€2,40 startkost",
            id="flat_with_20pct_vat",
        ),
        pytest.param(
            {
                "per_kwh": 0.38,
                "parking_per_hr": 3.0,
                "parking_grace_minutes": 15,
                "vat": 21.0,
            },
            "€0.46/kWh + €3.63/h parking after 15min",
            "0,46€/kWh + 3,63€/h stationnement après 15min",
            "€0,46/kWh + €3,63/u parkeren na 15min",
            id="energy_and_parking_with_21pct_vat",
        ),
        pytest.param(
            {"per_kwh": 0.45, "vat": 0.0},
            "€0.45/kWh",
            "0,45€/kWh",
            "€0,45/kWh",
            id="zero_vat_leaves_amount_unchanged",
        ),
    ],
)
def test_build_tariff_alt_text_with_vat(kwargs, expected_en, expected_fr, expected_nl):
    result = _build(**kwargs)
    assert result["en"] == expected_en
    assert result["fr"] == expected_fr
    assert result["nl"] == expected_nl


@pytest.mark.django_db
def test_create_solid_tariff_with_vat_shows_vat_inclusive_amount_in_alt_text(
    operator_fi_cpo,
):
    service = SolidTariffService()
    validated_data = {
        "external_id": "ALT-TEXT-VAT-1",
        "currency": "EUR",
        "price_per_kwh": 0.45,
        "price_per_hr": 6.0,
        "vat_percentage": 21.0,
        "ocpi_master": operator_fi_cpo,
        "msp": None,
    }

    solid_tariff = service.create(validated_data)

    alt_texts = {
        display_text.language: display_text.text
        for display_text in solid_tariff.ocpi_tariff.tariff_alt_text.all()
    }
    assert alt_texts["en"] == "€0.54/kWh + €7.26/h charging"
    assert alt_texts["fr"] == "0,54€/kWh + 7,26€/h recharge"
    assert alt_texts["nl"] == "€0,54/kWh + €7,26/u opladen"
