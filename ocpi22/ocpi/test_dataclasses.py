from datetime import datetime
import pytest
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpiconnector.party import Party


@pytest.fixture
def required_fields_data():
    return {
        "billed_to": Party("NL", "TNM"),
        "uid": "TOKEN123",
        "type": "RFID",
        "ocpi_master": None,
    }


@pytest.fixture
def all_fields_data():
    return {
        "valid": False,
        "billed_to": Party("BE", "ABC"),
        "uid": "TOKEN456",
        "type": "APP_USER",
        "ocpi_master": "test_master",
        "country_code": "BE",
        "party_id": "ABC",
        "whitelist": "ALWAYS",
        "visual_number": "123456",
        "issuer": "Test Issuer",
        "group_id": "Group1",
        "language": "fr",
        "default_profile_type": "GREEN",
        "energy_contract": "contract123",
        "contract_id": "ID123",
        "last_updated": datetime(2023, 1, 1, 12, 0, 0),
    }


@pytest.fixture
def minimal_token_data():
    return {
        "billed_to": Party("NL", "TNM"),
        "uid": "TOKEN789",
        "type": "RFID",
        "ocpi_master": None,
    }


def test_adhoc_token_from_dict_required_fields(required_fields_data):
    token = AdhocToken.from_dict(required_fields_data)
    assert token.valid is True  # Default when not specified
    assert token.billed_to == Party("NL", "TNM")
    assert token.uid == "TOKEN123"
    assert token.type == "RFID"
    assert token.ocpi_master is None
    assert token.country_code == ""
    assert token.party_id == ""
    assert token.whitelist == "NEVER"


def test_adhoc_token_from_dict_all_fields(all_fields_data):
    token = AdhocToken.from_dict(all_fields_data)
    assert token.valid is False
    assert token.billed_to == Party("BE", "ABC")
    assert token.uid == "TOKEN456"
    assert token.type == "APP_USER"
    assert token.ocpi_master == "test_master"
    assert token.country_code == "BE"
    assert token.party_id == "ABC"
    assert token.whitelist == "ALWAYS"
    assert token.visual_number == "123456"
    assert token.issuer == "Test Issuer"
    assert token.group_id == "Group1"
    assert token.language == "fr"
    assert token.default_profile_type == "GREEN"
    assert token.energy_contract == "contract123"
    assert token.contract_id == "ID123"
    assert token.last_updated == datetime(2023, 1, 1, 12, 0, 0)


def test_adhoc_token_methods(minimal_token_data):
    minimal_token = AdhocToken.from_dict(minimal_token_data)
    assert minimal_token.party_str() == str(Party("NL", "TNM"))
    assert minimal_token.get_party() == Party("NL", "TNM")
    assert str(minimal_token) == f"{str(Party('NL', 'TNM'))}: RFID TOKEN789"
    assert minimal_token.get("uid") == "TOKEN789"
    assert minimal_token.get("nonexistent", "default") == "default"
