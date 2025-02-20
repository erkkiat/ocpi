import pytest

from ocpi22.cpo.services import SolidTariffService


@pytest.fixture
def solid_tariff_service_instance():
    return SolidTariffService()


@pytest.mark.parametrize(
    "validated_data, expected_missing",
    [
        # Case: All fields are present (no "__isnull" should be added)
        (
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
        ),
        # Case: Some fields are missing or None
        (
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
        ),
        # Case: All fields are missing
        (
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
        ),
    ],
)
def test_set_missing_fields(
    solid_tariff_service_instance, validated_data, expected_missing
):
    print(validated_data)
    solid_tariff_service_instance._set_missing_fields(validated_data)
    print(validated_data)

    for key in expected_missing:
        assert f"{key}__isnull" in validated_data

    for key, value in validated_data.items():
        if not key.endswith("__isnull"):
            print(f"{key}: {value}")
            assert value is not None


@pytest.mark.parametrize(
    "per_minute_value, expected_result",
    [
        (0.5, 30.0),  # 0.5 per minute should be converted to 30.0 per hour
        (1.0, 60.0),  # 1.0 per minute should be converted to 60.0 per hour
        (None, None),  # If None is passed, the result should also be None
        ("", None),  # If an empty string is passed, the result should be None
        (
            "invalid",
            None,
        ),  # If an invalid string is passed, the result should also be None
    ],
)
def test_convert_to_hourly(
    solid_tariff_service_instance, per_minute_value, expected_result
):
    result = solid_tariff_service_instance._convert_to_hourly(per_minute_value)
    assert result == expected_result, f"Expected {expected_result}, but got {result}"
