import pytest
from django.core.exceptions import ValidationError

from generic.validators import (
    validate_country_code_alpha2,
    validate_country_code_alpha3,
)


class TestValidateCountryCodeAlpha2:
    @pytest.mark.parametrize(
        "country_code",
        [
            "FI",
            "NL",
            "DE",
            "US",
            "GB",
            "fi",
            "nl",
        ],
    )
    def test_accepts_valid_iso_3166_1_alpha2_codes(self, country_code):
        validate_country_code_alpha2(country_code)

    @pytest.mark.parametrize(
        "country_code",
        [
            "XX",
            "ZZ",
            "QQ",
            "A1",
            "123",
            "",
        ],
    )
    def test_raises_validation_error_for_invalid_alpha2_codes(self, country_code):
        with pytest.raises(ValidationError, match="is not a valid ISO 3166-1 alpha-2"):
            validate_country_code_alpha2(country_code)


class TestValidateCountryCodeAlpha3:
    @pytest.mark.parametrize(
        "country_code",
        [
            "FIN",
            "NLD",
            "DEU",
            "USA",
            "GBR",
            "fin",
            "nld",
        ],
    )
    def test_accepts_valid_iso_3166_1_alpha3_codes(self, country_code):
        validate_country_code_alpha3(country_code)

    @pytest.mark.parametrize(
        "country_code",
        [
            "XXX",
            "ZZZ",
            "QQQ",
            "AB",
            "1234",
            "",
        ],
    )
    def test_raises_validation_error_for_invalid_alpha3_codes(self, country_code):
        with pytest.raises(ValidationError, match="is not a valid ISO 3166-1 alpha-3"):
            validate_country_code_alpha3(country_code)
