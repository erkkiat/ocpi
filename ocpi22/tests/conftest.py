import pytest

from ocpi22.tests.factories import CredentialsRoleFactory


@pytest.fixture
def msp1():
    return CredentialsRoleFactory(country_code="DE", party_id="ICE")


@pytest.fixture
def msp2():
    return CredentialsRoleFactory(country_code="DE", party_id="ICD")


@pytest.fixture
def operator():
    return CredentialsRoleFactory(country_code="FI", party_id="CPO")


@pytest.fixture
def smp1_tariff():
    return {
        "id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.690,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "vat_percentage": 20.0,
        "msps": ["DE*ICE", "DE*ICD"],
    }


@pytest.fixture
def smp1_updated_tariff():
    return {
        "id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.703,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "vat_percentage": 20.0,
        "msps": ["DE*ICE"],
    }


@pytest.fixture
def smp1_patched_tariff():
    return {
        "currency": "USD",
    }


@pytest.fixture
def solid_tariff_smp1_msp1_updated_data(operator, msp1):
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.703,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "vat_percentage": 20.0,
        "msp": msp1,
        "operator": operator,
        "archived": False,
    }


@pytest.fixture
def solid_tariff_smp1_msp1_data(operator, msp1):
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.690,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "vat_percentage": 20.0,
        "msp": msp1,
        "operator": operator,
        "archived": False,
    }


@pytest.fixture
def solid_tariff_smp1_msp2_data(operator, msp2):
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.690,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "vat_percentage": 20.0,
        "msp": msp2,
        "operator": operator,
        "archived": False,
    }
