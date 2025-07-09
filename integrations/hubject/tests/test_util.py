import pytest

from integrations.hubject.util import decode_country_code_and_party_id


@pytest.mark.parametrize(
    "provider_id, expected",
    [
        (None, (None, None)),
        ("US*ABC", ("US", "ABC")),
        ("DE-XYZ", ("DE", "XYZ")),
        ("FR123", ("FR", "123")),
    ],
)
def test_decode_valid(provider_id, expected):
    assert decode_country_code_and_party_id(provider_id) == expected


def test_decode_invalid_raises():
    with pytest.raises(ValueError) as exc:
        decode_country_code_and_party_id("INVALID_FORMAT")
    assert "Invalid ProviderID format" in str(exc.value)
