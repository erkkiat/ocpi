from datetime import datetime

import pytest
from pydantic import ValidationError

from ocpi22.cpo.schemas import (
    LocationIn,
    EVSE,
    Connector,
    OpeningTimes,
    RegularHours,
)
from ocpi22.test_tariff_location_and_evse import load_example


@pytest.fixture
def location_data():
    return {
        "country_code": "BE",
        "party_id": "BEC",
        "uid": "LOC1",
        "publish": True,
        "address": "F.Rooseveltlaan 3A",
        "city": "Gent",
        "postal_code": "9000",
        "state": "East Flanders",
        "country": "BEL",
        "coordinates": {"latitude": "51.047599", "longitude": "3.729944"},
        "evses": [],
        "time_zone": "Europe/Brussels",
        "last_updated": "2015-06-29T20:39:09Z",
        "roaming_enabled": True,
    }


@pytest.fixture
def connector_data():
    return {
        "id": "1",
        "standard": "IEC_62196_T2",
        "format": "CABLE",
        "power_type": "AC_3_PHASE",
        "max_voltage": 220,
        "max_amperage": 16,
        "max_electric_power": 3500,
        "tariff_ids": ["11"],
        "last_updated": datetime(2023, 10, 1, 12, 0),
    }


@pytest.fixture
def evse_data(connector_data):
    return {
        "uid": "3256",
        "evse_id": "BE*BEC*E041503001",
        "status": "AVAILABLE",
        "last_updated": datetime(2023, 10, 1, 12, 0),
        "connectors": [],
        "capabilities": None,
    }


@pytest.fixture
def invalid_country(location_data):
    location_data.pop("country")
    location_data["country"] = "INVALID"
    return location_data


@pytest.fixture
def invalid_type(location_data):
    location_data.pop("country")
    location_data["country"] = 10
    return location_data


def test_location_in_schema_valid_data_does_not_raise_validation_error():
    data = load_example("data/examples/location_example.json")
    location = LocationIn(**data)
    assert location.country == "BEL"


def test_location_in_schema_valid_data_with_evse_does_not_raise_validation_error():
    data = load_example("data/examples/location_example_added_evse.json")
    location = LocationIn(**data)
    assert location.country == "BEL"


def test_location_in_schema_valid_data_with_connector_does_not_raise_validation_error():
    data = load_example("data/examples/location_example_added_connector.json")
    location = LocationIn(**data)
    assert location.country == "BEL"


def test_location_in_schema_valid_data_with_opening_hours_does_not_raise_validation_error():
    data = load_example(
        "data/examples/location_example_parking_garage_opening_hours.json"
    )
    location = LocationIn(**data)
    assert location.country == "SWE"


def test_location_in_schema_invalid_country_raises_value_error(invalid_country):
    with pytest.raises(ValueError, match="INVALID is not a valid country"):
        LocationIn(**invalid_country)


def test_location_in_schema_none_country_raises_validation_error(location_data):
    location_data.pop("country")
    with pytest.raises(ValidationError):
        LocationIn(**location_data)


def test_location_in_schema_invalid_parking_type_raises_value_error(location_data):
    location_data["parking_type"] = "INVALID"
    with pytest.raises(ValidationError):
        LocationIn(**location_data)


def test_location_in_roaming_enabled_field_is_optional(location_data):
    location_data.pop("roaming_enabled")
    location = LocationIn(**location_data)
    assert location.roaming_enabled is True


def test_evse_schema_valid_data(evse_data):
    evse = EVSE(**evse_data)
    assert evse.evse_id == evse_data["evse_id"]


def test_evse_schema_invalid_status_raises_value_error(evse_data):
    evse_data["status"] = "INVALID"
    with pytest.raises(ValidationError):
        EVSE(**evse_data)


def test_evse_schema_none_status_raises_validation_error(evse_data):
    evse_data.pop("status")
    with pytest.raises(ValidationError):
        EVSE(**evse_data)


def test_connector_schema_valid_data(connector_data):
    connector = Connector(**connector_data)
    assert connector.uid == connector_data["id"]


def test_connector_schema_invalid_standard_raises_value_error(connector_data):
    connector_data["standard"] = "INVALID"
    with pytest.raises(ValidationError):
        Connector(**connector_data)


def test_connector_schema_none_standard_raises_validation_error(connector_data):
    connector_data.pop("standard")
    with pytest.raises(ValidationError):
        Connector(**connector_data)


def test_connector_schema_invalid_format_raises_value_error(connector_data):
    connector_data["format"] = "INVALID"
    with pytest.raises(ValidationError):
        Connector(**connector_data)


def test_connector_schema_none_format_raises_validation_error(connector_data):
    connector_data.pop("format")
    with pytest.raises(ValidationError):
        Connector(**connector_data)


def test_connector_schema_invalid_power_type_raises_value_error(connector_data):
    connector_data["power_type"] = "INVALID"
    with pytest.raises(ValidationError):
        Connector(**connector_data)


def test_connector_schema_none_power_type_raises_validation_error(connector_data):
    connector_data.pop("power_type")
    with pytest.raises(ValidationError):
        Connector(**connector_data)


def test_regular_hours_and_exceptional_openings_closings_are_not_mandatory_when_twentyfourseven_is_true():
    opening_times = OpeningTimes(twentyfourseven=True)
    assert opening_times.regular_hours is None


def test_regular_hours_is_not_none_when_twentyfourseven_is_false_returns_opening_times_successfully():
    opening_times = OpeningTimes(
        twentyfourseven=False,
        regular_hours=[
            RegularHours(weekday=1, period_begin="08:00", period_end="20:00")
        ],
        exceptional_openings=None,
        exceptional_closings=None,
    )
    assert opening_times.regular_hours is not None
    assert len(opening_times.regular_hours) == 1


def test_regular_hours_none_when_twentyfourseven_is_false_raises_validation_error():
    with pytest.raises(ValidationError) as exc_info:
        OpeningTimes(
            twentyfourseven=False,
            regular_hours=None,
            exceptional_openings=None,
            exceptional_closings=None,
        )

    error_msg = str(exc_info.value)
    assert "regular_hours is required when twentyfourseven is False" in error_msg


def test_regular_hours_empty_when_twentyfourseven_is_false_raises_validation_error():
    with pytest.raises(ValidationError) as exc_info:
        OpeningTimes(
            twentyfourseven=False,
            regular_hours=[],
            exceptional_openings=None,
            exceptional_closings=None,
        )

    error_msg = str(exc_info.value)
    assert "regular_hours is required when twentyfourseven is False" in error_msg
