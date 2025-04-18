from datetime import datetime
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpiconnector.party import Party


def test_adhoc_token_from_dict_required_fields():
    # Setup data with only required fields
    data = {
        "billed_to": Party("NL", "TNM"),
        "uid": "TOKEN123",
        "type": "RFID",
        "ocpi_master": None,
    }

    # Call the method
    token = AdhocToken.from_dict(data)

    # Assert results
    assert token.valid is True  # Default when not specified
    assert token.billed_to == Party("NL", "TNM")
    assert token.uid == "TOKEN123"
    assert token.type == "RFID"
    assert token.ocpi_master is None
    assert token.country_code == ""
    assert token.party_id == ""
    assert token.whitelist == "NEVER"


def test_adhoc_token_from_dict_all_fields():
    # Setup data with all fields
    data = {
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

    # Call the method
    token = AdhocToken.from_dict(data)

    # Assert results
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


def test_adhoc_token_methods():
    # Setup
    token = AdhocToken.from_dict(
        {
            "billed_to": Party("NL", "TNM"),
            "uid": "TOKEN789",
            "type": "RFID",
            "ocpi_master": None,
        }
    )

    # Test party_str method
    assert token.party_str() == str(Party("NL", "TNM"))

    # Test get_party method
    assert token.get_party() == Party("NL", "TNM")

    # Test __str__ method
    assert str(token) == f"{str(Party('NL', 'TNM'))}: RFID TOKEN789"

    # Test get method
    assert token.get("uid") == "TOKEN789"
    assert token.get("nonexistent", "default") == "default"
