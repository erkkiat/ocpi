import pytest

from ocpi22.tests.factories import (
    CredentialsRoleFactory,
    TariffFactory,
    SolidTariffFactory,
)


@pytest.fixture
def smp1_solid_tariff_data():
    return {
        "id": 1,
        "uid": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.52,
        "price_per_min": 0.42,
        "price_flat": 0.3,
        "vat": 20.0,
    }


@pytest.fixture
def smp2_solid_tariff_data():
    return {
        "id": 2,
        "uid": "SMP2",
        "currency": "EUR",
        "price_per_kwh": 0.52,
        "price_per_min": 0.42,
        "price_flat": 0.3,
        "vat": 20.0,
    }


@pytest.fixture
def smp1_solid_tariff():
    return SolidTariffFactory(
        id=1,
        uid="SMP1",
        currency="EUR",
        price_per_kwh=0.52,
        price_per_min=0.42,
        price_flat=0.3,
        vat=20.0,
    )


@pytest.fixture
def smp2_solid_tariff():
    return SolidTariffFactory(
        id=2,
        uid="SMP2",
        currency="EUR",
        price_per_kwh=0.52,
        price_per_min=0.42,
        price_flat=0.3,
        vat=20.0,
    )


@pytest.fixture
def smp1_solid_tariff_with_msp1():
    return SolidTariffFactory(
        id=1,
        uid="SMP1",
        currency="EUR",
        price_per_kwh=0.52,
        price_per_min=0.42,
        price_flat=0.3,
        vat=20.0,
        msp=CredentialsRoleFactory(country_code="DE", party_id="SMP"),
    )


@pytest.fixture
def tariff_smp1():
    return TariffFactory(
        uid="SMP1",
    )
