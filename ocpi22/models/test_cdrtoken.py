import pytest


@pytest.mark.django_db
def test_cdrtoken_string_conversion_to_show_correct_data(default_cdrtoken):
    assert (
        str(default_cdrtoken)
        == 'FI*MSP (EMSP) / ID "DEADC0DE" / contract: "CONTRACT-12345"'
    )
