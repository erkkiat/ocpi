import copy
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.forms import model_to_dict

from ocpi22.cpo.repositories import SolidTariffRepository
from ocpi22.cpo.services import SolidTariffService
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.location import Connector
from ocpi22.tests.factories import ConnectorFactory, TariffFactory, SolidTariffFactory

from ocpi22.credentials.util import find_endpoints_by_roles


@pytest.fixture
def solid_tariff_service_instance():
    return SolidTariffService()


@pytest.fixture
def connector_with_tariff(
    solid_tariff_service_instance, smp1_solid_tariff_validated_json
):
    old_solid_tariff = solid_tariff_service_instance.create(
        smp1_solid_tariff_validated_json
    )
    return ConnectorFactory(
        uid="ConnectorWithTariff",
        tariff_ids=[old_solid_tariff.ocpi_tariff],
    )


@pytest.mark.parametrize(
    "validated_data, expected_missing",
    [
        pytest.param(
            {
                "price_per_kwh": 0.5,
                "price_per_min": 0.2,
                "price_flat": 1.0,
                "parking_price_per_min": 0.3,
                "vat_percentage": 20.0,
                "parking_grace_period": 15,
                "msp": "DE*ICE",
            },
            [],
            id="All fields are present",
        ),
        pytest.param(
            {
                "price_per_kwh": None,
                "price_per_min": 0.2,
                "price_flat": None,
                "parking_price_per_min": 0.3,
                "vat_percentage": None,
                "parking_grace_period": 15,
                "msp": None,
            },
            ["price_per_kwh", "price_flat", "vat_percentage", "msp"],
            id="Some fields are missing or None",
        ),
        pytest.param(
            {},
            [
                "price_per_kwh",
                "price_per_min",
                "price_flat",
                "parking_price_per_min",
                "vat_percentage",
                "parking_grace_period",
                "msp",
            ],
            id="All fields are missing",
        ),
    ],
)
def test_set_missing_fields(
    solid_tariff_service_instance, validated_data, expected_missing
):
    solid_tariff_service_instance._set_missing_fields(validated_data)

    for key in expected_missing:
        assert f"{key}__isnull" in validated_data

    for key, value in validated_data.items():
        if not key.endswith("__isnull"):
            print(f"{key}: {value}")
            assert value is not None


@pytest.mark.parametrize(
    "per_minute_value, expected_result",
    [
        (0.5, 30.0),
        (1.0, 60.0),
        (None, None),
        ("", None),
        (
            "invalid",
            None,
        ),
    ],
)
def test_convert_to_hourly(
    solid_tariff_service_instance, per_minute_value, expected_result
):
    result = solid_tariff_service_instance._convert_to_hourly(per_minute_value)
    assert result == expected_result, f"Expected {expected_result}, but got {result}"


@pytest.mark.django_db
def test_create_returns_solid_tariff_with_valid_data(
    solid_tariff_service_instance, smp1_solid_tariff_validated_json
):
    solid_tariff = solid_tariff_service_instance.create(
        smp1_solid_tariff_validated_json
    )

    st_dict = model_to_dict(solid_tariff)
    st_dict.pop("id")
    st_dict.pop("last_updated")
    msp_id = st_dict.pop("msp")
    st_dict.pop("ocpi_tariff")
    operator_id = st_dict.pop("operator")
    st_dict["operator"] = CredentialsRole.objects.get(pk=operator_id)
    st_dict["msp"] = CredentialsRole.objects.get(pk=msp_id)

    assert st_dict == smp1_solid_tariff_validated_json


@pytest.mark.django_db
def test_create_raises_exception_on_invalid_data(solid_tariff_service_instance):
    with pytest.raises(ValidationError):
        solid_tariff_service_instance.create({})


@pytest.mark.django_db
def test_user_sending_same_tariff_as_latest_does_not_create_a_new_tariff(
    smp1_msp1_solid_tariff_with_all_records,
    solid_tariff_service_instance,
    smp1_solid_tariff_validated_json,
):
    with patch.object(
        solid_tariff_service_instance, "_create_new_tariff"
    ) as mock_create_new_tariff:
        solid_tariff_service_instance.create(smp1_solid_tariff_validated_json)

        mock_create_new_tariff.assert_not_called()


@pytest.mark.django_db
def test_user_sending_same_tariff_as_expired_does_create_a_new_tariff(
    smp1_msp1_solid_tariff_with_all_records,
    solid_tariff_service_instance,
    smp1_solid_tariff_validated_json,
):
    # Original is modified after create method, therefore keeping copies to replicate same scenario
    original_solid_tariff_copy = copy.deepcopy(smp1_solid_tariff_validated_json)

    new_solid_tariff = copy.deepcopy(smp1_solid_tariff_validated_json)
    new_solid_tariff["price_per_kwh"] = 0.99

    solid_tariff_service_instance.create(smp1_solid_tariff_validated_json)

    solid_tariff_service_instance.create(new_solid_tariff)

    with patch.object(
        solid_tariff_service_instance, "_create_new_tariff"
    ) as mock_create_new_tariff:
        solid_tariff_service_instance.create(original_solid_tariff_copy)

        mock_create_new_tariff.assert_called()


@pytest.mark.django_db
def test_create_solid_tariff_with_same_external_id_replaces_ocpi_tariff_in_connectors(
    solid_tariff_service_instance,
    smp1_solid_tariff_validated_json,
    connector_with_tariff,
):
    find_endpoints_by_roles.cache_clear()

    smp1_solid_tariff_validated_json["price_per_kwh"] = 100
    smp1_solid_tariff_validated_json["ocpi_master"] = smp1_solid_tariff_validated_json[
        "operator"
    ]

    new_solid_tariff = solid_tariff_service_instance.create(
        smp1_solid_tariff_validated_json
    )

    connector = Connector.get_if_exists(uid=connector_with_tariff.uid)
    assert connector.get_tariffs().first() == new_solid_tariff.ocpi_tariff


@pytest.mark.django_db
def test_find_by_ocpi_tariff_id_found():
    ocpi_tariff = TariffFactory(uid="SMP1")
    solid_tariff = SolidTariffFactory(external_id="SD1", ocpi_tariff=ocpi_tariff)
    result = SolidTariffRepository.find_by_ocpi_tariff_id("SMP1")
    assert result == solid_tariff


@pytest.mark.django_db
def test_find_by_ocpi_tariff_id_not_found():
    result = SolidTariffRepository.find_by_ocpi_tariff_id("nonexistent_uid")
    assert result is None
