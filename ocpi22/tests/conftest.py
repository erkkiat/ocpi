import pytest
from rest_framework.test import APIClient
from ocpi22.tests.factories import CredentialsRoleFactory


@pytest.fixture
def client():
    return APIClient()


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
def smp1_solid_tariff_with_all_records():
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.690,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "parking_price_per_min": 0.54,
        "parking_grace_period": 100,
        "vat_percentage": 20.0,
        "msp": "DE*ICE",
    }


@pytest.fixture
def smp1_msp1_solid_tariff_with_all_records(msp_de_ice, operator_fi_cpo):
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.690,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "parking_price_per_min": 0.54,
        "parking_grace_period": 100,
        "vat_percentage": 20.0,
        "msp": msp_de_ice,
        "operator": operator_fi_cpo,
    }


@pytest.fixture
def smp1_solid_tariff_response_with_all_records():
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": "0.69",
        "price_per_min": "0.42",
        "price_flat": "0.56",
        "parking_price_per_min": "0.54",
        "parking_grace_period": 100,
        "vat_percentage": "20.0",
        "msp": "DE*ICE",
    }


@pytest.fixture
def smp1_solid_tariff_minimal_records():
    return {
        "external_id": "SMP1",
        "currency": "EUR",
    }


@pytest.fixture
def smp1_solid_tariff_response_with_minimal_records():
    return {
        "currency": "EUR",
        "external_id": "SMP1",
        "parking_grace_period": None,
        "parking_price_per_min": None,
        "price_flat": None,
        "price_per_kwh": None,
        "price_per_min": None,
        "vat_percentage": None,
    }


@pytest.fixture
def smp1_solid_tariff_zero_pricing():
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0,
        "price_per_min": 0,
        "price_flat": 0,
        "parking_price_per_min": 0,
        "parking_grace_period": 0,
        "vat_percentage": 0,
    }


@pytest.fixture
def smp1_solid_tariff_response_with_zero_pricing():
    return {
        "currency": "EUR",
        "external_id": "SMP1",
        "parking_grace_period": 0,
        "parking_price_per_min": "0",
        "price_flat": "0",
        "price_per_kwh": "0",
        "price_per_min": "0",
        "vat_percentage": "0",
    }


@pytest.fixture
def smp1_solid_tariff_minus_pricing():
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": -10,
        "price_per_min": -10,
        "price_flat": -10,
        "parking_price_per_min": -10,
        "parking_grace_period": -10,
        "vat_percentage": 10,
    }


@pytest.fixture
def smp1_solid_tariff_response_with_minus_pricing():
    return {
        "price_per_kwh": ["price_per_kwh cannot be negative."],
        "price_per_min": ["price_per_min cannot be negative."],
        "price_flat": ["price_flat cannot be negative."],
        "parking_price_per_min": ["parking_price_per_min cannot be negative."],
        "parking_grace_period": ["Ensure this value is greater than or equal to 0."],
    }


@pytest.fixture
def smp1_solid_tariff_invalid_currency():
    return {
        "external_id": "SMP1",
        "currency": "INVALID",
        "price_per_kwh": -10,
        "price_per_min": -10,
        "price_flat": -10,
        "parking_price_per_min": -10,
        "parking_grace_period": -10,
        "vat_percentage": -10,
        "msp": None,
    }


@pytest.fixture
def smp1_solid_tariff_blank_external_id():
    return {
        "external_id": "SMP1",
        "currency": "INVALID",
        "price_per_kwh": -10,
        "price_per_min": -10,
        "price_flat": -10,
        "parking_price_per_min": -10,
        "parking_grace_period": -10,
        "vat_percentage": -10,
        "msp": None,
    }


@pytest.fixture
def smp1_tariff():
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.690,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "parking_price_per_min": 0.54,
        "parking_grace_period": 100,
        "vat_percentage": 20.0,
        "msp": "DE*ICE",
    }


@pytest.fixture
def smp1_tariff_no_msp():
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.690,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "parking_price_per_min": 0.54,
        "parking_grace_period": 100,
        "vat_percentage": 20.0,
    }


@pytest.fixture
def smp1_tariff_data_with_no_external_id():
    return {
        "currency": "EUR",
        "price_per_kwh": 0.703,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "parking_price_per_min": 0.54,
        "parking_grace_period": 100,
        "vat_percentage": 20.0,
        "msp": "DE*ICE",
    }


@pytest.fixture
def smp1_tariff_update_data_with_no_external_id():
    return {
        "currency": "EUR",
        "price_per_kwh": 0.103,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "parking_price_per_min": 0.54,
        "parking_grace_period": 100,
        "vat_percentage": 20.0,
        "msp": "DE*ICE",
    }


@pytest.fixture
def smp1_update_tariff():
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.703,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "parking_price_per_min": 0.54,
        "parking_grace_period": 100,
        "vat_percentage": 20.0,
        "msp": "DE*ICE",
    }


@pytest.fixture
def smp1_update_tariff_no_msp():
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": "0.703",
        "price_per_min": "0.42",
        "price_flat": "0.56",
        "parking_price_per_min": 0.54,
        "parking_grace_period": 100,
        "vat_percentage": "20.0",
    }


@pytest.fixture
def smp1_patch_tariff_payload():
    return {
        "currency": "USD",
    }


@pytest.fixture
def solid_tariff_smp1_msp1_update_data(operator_fi_cpo, msp_de_ice):
    return {
        "external_id": "SMP1",
        "currency": "EUR",
        "price_per_kwh": 0.703,
        "price_per_min": 0.42,
        "price_flat": 0.56,
        "parking_price_per_min": 0.54,
        "parking_grace_period": 100,
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
        "parking_price_per_min": 0.54,
        "parking_grace_period": 100,
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
        "parking_price_per_min": 0.54,
        "parking_grace_period": 100,
        "vat_percentage": 20.0,
        "msp": msp_de_icd,
        "operator": operator_fi_cpo,
        "archived": False,
    }
