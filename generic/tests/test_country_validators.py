import pytest
from django.core.exceptions import ValidationError

from generic.validators import (
    validate_country_code_alpha2,
    validate_country_code_alpha3,
    validate_latitude,
    validate_longitude,
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


class TestValidateLatitude:
    @pytest.mark.parametrize(
        "latitude",
        [
            "0",
            "47.662249",
            "-90",
            "90",
            "-45.123456",
            "0.0",
        ],
    )
    def test_accepts_valid_latitude_values(self, latitude):
        validate_latitude(latitude)

    @pytest.mark.parametrize(
        "latitude",
        [
            "90.1",
            "-90.1",
            "180",
            "-180",
            "999",
        ],
    )
    def test_raises_validation_error_for_out_of_range_latitude(self, latitude):
        with pytest.raises(ValidationError, match="Must be between -90 and 90"):
            validate_latitude(latitude)

    @pytest.mark.parametrize(
        "latitude",
        [
            "abc",
            "12.34.56",
            "",
            "N47",
        ],
    )
    def test_raises_validation_error_for_non_numeric_latitude(self, latitude):
        with pytest.raises(ValidationError, match="Must be a decimal number"):
            validate_latitude(latitude)


class TestValidateLongitude:
    @pytest.mark.parametrize(
        "longitude",
        [
            "0",
            "9.360922",
            "-180",
            "180",
            "-122.419416",
            "0.0",
        ],
    )
    def test_accepts_valid_longitude_values(self, longitude):
        validate_longitude(longitude)

    @pytest.mark.parametrize(
        "longitude",
        [
            "180.1",
            "-180.1",
            "360",
            "-999",
        ],
    )
    def test_raises_validation_error_for_out_of_range_longitude(self, longitude):
        with pytest.raises(ValidationError, match="Must be between -180 and 180"):
            validate_longitude(longitude)

    @pytest.mark.parametrize(
        "longitude",
        [
            "abc",
            "12.34.56",
            "",
            "E9",
        ],
    )
    def test_raises_validation_error_for_non_numeric_longitude(self, longitude):
        with pytest.raises(ValidationError, match="Must be a decimal number"):
            validate_longitude(longitude)
