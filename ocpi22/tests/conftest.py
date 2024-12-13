import pytest

from ocpi22.tests.factories import CredentialsRoleFactory


@pytest.fixture
def msp_de_ice():
    return CredentialsRoleFactory(country_code="DE", party_id="ICE")


@pytest.fixture
def msp_de_icd():
    return CredentialsRoleFactory(country_code="DE", party_id="ICD")


@pytest.fixture
def operator_fi_cpo():
    return CredentialsRoleFactory(country_code="FI", party_id="CPO")


@pytest.fixture
def smp1_tariff():
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.690,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "vat_percentage": 20.0,
        "msp": "DE*ICE",
    }


@pytest.fixture
def smp1_tariff_data_with_no_external_id():
    return {
        "currency": "EUR",
        "price_per_kwh": 0.703,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "vat_percentage": 20.0,
        "msp": "DE*ICE",
    }


@pytest.fixture
def smp1_tariff_updated_data_with_no_external_id():
    return {
        "currency": "EUR",
        "price_per_kwh": 0.103,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "vat_percentage": 20.0,
        "msp": "DE*ICE",
    }


@pytest.fixture
def smp1_updated_tariff():
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.703,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "vat_percentage": 20.0,
        "msp": "DE*ICE",
    }


@pytest.fixture
def smp1_patched_tariff():
    return {
        "currency": "USD",
    }


@pytest.fixture
def solid_tariff_smp1_msp1_updated_data(operator_fi_cpo, msp_de_ice):
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.703,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "vat_percentage": 20.0,
        "msp": msp_de_ice,
        "operator": operator_fi_cpo,
        "archived": False,
    }


@pytest.fixture
def solid_tariff_smp1_msp1_data(operator_fi_cpo, msp_de_ice):
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.690,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "vat_percentage": 20.0,
        "msp": msp_de_ice,
        "operator": operator_fi_cpo,
        "archived": False,
    }


@pytest.fixture
def solid_tariff_smp1_msp2_data(operator_fi_cpo, msp_de_icd):
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.690,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "vat_percentage": 20.0,
        "msp": msp_de_icd,
        "operator": operator_fi_cpo,
        "archived": False,
    }
