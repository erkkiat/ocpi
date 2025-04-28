from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.forms import model_to_dict

from ocpi22.cpo.services import SolidTariffService
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.location import Connector
from ocpi22.ocpi.serializers import TariffSerializer
from ocpi22.tests.factories import ConnectorFactory

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
def test_create_returns_solid_tariff_with_vali_data(
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
def test_create_returns_same_object_if_exists(
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
def test_create_solid_tariff_with_same_external_id_updates_connectors_with_new_ocpi_tariff_id(
    solid_tariff_service_instance,
    smp1_solid_tariff_validated_json,
    connector_with_tariff,
):
    find_endpoints_by_roles.cache_clear()

    smp1_solid_tariff_validated_json["price_per_kwh"] = 100
    smp1_solid_tariff_validated_json["ocpi_master"] = smp1_solid_tariff_validated_json[
        "operator"
    ]

    with patch(
        "ocpi22.ocpi.util.OcpiModule.send_background_update"
    ) as mock_send_background_update:
        new_solid_tariff = solid_tariff_service_instance.create(
            smp1_solid_tariff_validated_json
        )

        connector = Connector.get_if_exists(uid=connector_with_tariff.uid)
        assert connector.get_tariffs().first() == new_solid_tariff.ocpi_tariff

        assert mock_send_background_update.call_count >= 2

        tariff_data = TariffSerializer(instance=new_solid_tariff.ocpi_tariff).data

        tariff_call_found = False
        for call_args in mock_send_background_update.call_args_list:
            args = call_args[0]
            if (
                args
                and isinstance(args[0], dict)
                and args[0].get("id") == tariff_data.get("id")
            ):
                tariff_call_found = True
                break

        assert tariff_call_found, "No call found for the tariff update"

        location_call_found = False
        for call_args in mock_send_background_update.call_args_list:
            args = call_args[0]
            if args and isinstance(args[0], dict) and "evses" in args[0]:
                location_call_found = True
                for evse in args[0]["evses"]:
                    for connector_data in evse.get("connectors", []):
                        if connector_data.get("id") == connector_with_tariff.uid:
                            assert (
                                new_solid_tariff.ocpi_tariff.uid
                                in connector_data.get("tariff_ids", [])
                            )
                break

        assert location_call_found, "No call found for the location update"
