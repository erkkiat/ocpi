import pytest
from django.core.exceptions import ValidationError

from ocpi22.tests.factories import TerminalFactory


@pytest.mark.django_db
class TestTerminalValidators:
    @pytest.mark.parametrize("country_code", ["FI", "NL", "DE", "US"])
    def test_save_succeeds_with_valid_alpha2_country_code(self, country_code):
        terminal = TerminalFactory(country_code=country_code)
        assert terminal.pk is not None
        assert terminal.country_code == country_code

    @pytest.mark.parametrize("country_code", ["XX", "ZZ", "QQ", "A1"])
    def test_save_raises_validation_error_with_invalid_alpha2_country_code(
        self, country_code
    ):
        with pytest.raises(ValidationError, match="is not a valid ISO 3166-1 alpha-2"):
            TerminalFactory(country_code=country_code)

    def test_save_succeeds_with_null_country_code(self):
        terminal = TerminalFactory(country_code=None)
        assert terminal.pk is not None
        assert terminal.country_code is None

    def test_save_succeeds_with_blank_country_code(self):
        terminal = TerminalFactory(country_code="")
        assert terminal.pk is not None
        assert terminal.country_code == ""

    @pytest.mark.parametrize("country", ["FIN", "NLD", "DEU", "USA"])
    def test_save_succeeds_with_valid_alpha3_country(self, country):
        terminal = TerminalFactory(country=country)
        assert terminal.pk is not None
        assert terminal.country == country

    @pytest.mark.parametrize("country", ["XXX", "ZZZ", "QQQ", "AB"])
    def test_save_raises_validation_error_with_invalid_alpha3_country(self, country):
        with pytest.raises(ValidationError, match="is not a valid ISO 3166-1 alpha-3"):
            TerminalFactory(country=country)

    def test_save_succeeds_with_null_country(self):
        terminal = TerminalFactory(country=None)
        assert terminal.pk is not None
        assert terminal.country is None

    def test_save_succeeds_with_blank_country(self):
        terminal = TerminalFactory(country="")
        assert terminal.pk is not None
        assert terminal.country == ""

    def test_update_raises_validation_error_when_country_code_changed_to_invalid(self):
        terminal = TerminalFactory(country_code="FI")
        terminal.country_code = "XX"
        with pytest.raises(ValidationError, match="is not a valid ISO 3166-1 alpha-2"):
            terminal.save()

    def test_update_raises_validation_error_when_country_changed_to_invalid(self):
        terminal = TerminalFactory(country="FIN")
        terminal.country = "XXX"
        with pytest.raises(ValidationError, match="is not a valid ISO 3166-1 alpha-3"):
            terminal.save()

    def test_update_succeeds_when_country_code_changed_to_valid(self):
        terminal = TerminalFactory(country_code="FI")
        terminal.country_code = "DE"
        terminal.save()
        terminal.refresh_from_db()
        assert terminal.country_code == "DE"

    def test_update_succeeds_when_country_changed_to_valid(self):
        terminal = TerminalFactory(country="FIN")
        terminal.country = "DEU"
        terminal.save()
        terminal.refresh_from_db()
        assert terminal.country == "DEU"

    @pytest.mark.parametrize("latitude", ["47.662249", "0", "-90", "90"])
    def test_save_succeeds_with_valid_latitude(self, latitude):
        terminal = TerminalFactory(latitude=latitude)
        assert terminal.pk is not None
        assert terminal.latitude == latitude

    @pytest.mark.parametrize("latitude", ["90.1", "-90.1", "180", "999"])
    def test_save_raises_validation_error_with_out_of_range_latitude(self, latitude):
        with pytest.raises(ValidationError, match="Must be between -90 and 90"):
            TerminalFactory(latitude=latitude)

    @pytest.mark.parametrize("latitude", ["abc", "12.34.56", "N47"])
    def test_save_raises_validation_error_with_non_numeric_latitude(self, latitude):
        with pytest.raises(ValidationError, match="Must be a decimal number"):
            TerminalFactory(latitude=latitude)

    def test_save_succeeds_with_null_latitude(self):
        terminal = TerminalFactory(latitude=None)
        assert terminal.pk is not None
        assert terminal.latitude is None

    def test_save_succeeds_with_blank_latitude(self):
        terminal = TerminalFactory(latitude="")
        assert terminal.pk is not None
        assert terminal.latitude == ""

    @pytest.mark.parametrize("longitude", ["9.360922", "0", "-180", "180"])
    def test_save_succeeds_with_valid_longitude(self, longitude):
        terminal = TerminalFactory(longitude=longitude)
        assert terminal.pk is not None
        assert terminal.longitude == longitude

    @pytest.mark.parametrize("longitude", ["180.1", "-180.1", "360", "-999"])
    def test_save_raises_validation_error_with_out_of_range_longitude(self, longitude):
        with pytest.raises(ValidationError, match="Must be between -180 and 180"):
            TerminalFactory(longitude=longitude)

    @pytest.mark.parametrize("longitude", ["abc", "12.34.56", "E9"])
    def test_save_raises_validation_error_with_non_numeric_longitude(self, longitude):
        with pytest.raises(ValidationError, match="Must be a decimal number"):
            TerminalFactory(longitude=longitude)

    def test_save_succeeds_with_null_longitude(self):
        terminal = TerminalFactory(longitude=None)
        assert terminal.pk is not None
        assert terminal.longitude is None

    def test_save_succeeds_with_blank_longitude(self):
        terminal = TerminalFactory(longitude="")
        assert terminal.pk is not None
        assert terminal.longitude == ""

    def test_update_raises_validation_error_when_latitude_changed_to_invalid(self):
        terminal = TerminalFactory(latitude="47.662249")
        terminal.latitude = "999"
        with pytest.raises(ValidationError, match="Must be between -90 and 90"):
            terminal.save()

    def test_update_raises_validation_error_when_longitude_changed_to_invalid(self):
        terminal = TerminalFactory(longitude="9.360922")
        terminal.longitude = "999"
        with pytest.raises(ValidationError, match="Must be between -180 and 180"):
            terminal.save()

    def test_update_succeeds_when_latitude_changed_to_valid(self):
        terminal = TerminalFactory(latitude="47.662249")
        terminal.latitude = "-33.8688"
        terminal.save()
        terminal.refresh_from_db()
        assert terminal.latitude == "-33.8688"

    def test_update_succeeds_when_longitude_changed_to_valid(self):
        terminal = TerminalFactory(longitude="9.360922")
        terminal.longitude = "151.2093"
        terminal.save()
        terminal.refresh_from_db()
        assert terminal.longitude == "151.2093"

    @pytest.mark.parametrize("value", ["caf\u00e9", "\u20ac10", "na\u00efve"])
    def test_save_raises_validation_error_when_terminal_id_contains_non_ascii(
        self, value
    ):
        with pytest.raises(ValidationError, match="must contain only ASCII"):
            TerminalFactory(terminal_id=value)

    @pytest.mark.parametrize("value", ["caf\u00e9", "\u20ac10", "na\u00efve"])
    def test_save_raises_validation_error_when_customer_reference_contains_non_ascii(
        self, value
    ):
        with pytest.raises(ValidationError, match="must contain only ASCII"):
            TerminalFactory(customer_reference=value)

    @pytest.mark.parametrize("value", ["caf\u00e9", "\u20ac10", "na\u00efve"])
    def test_save_raises_validation_error_when_party_id_contains_non_ascii(self, value):
        with pytest.raises(ValidationError, match="must contain only ASCII"):
            TerminalFactory(party_id=value)

    def test_save_succeeds_with_null_customer_reference(self):
        terminal = TerminalFactory(customer_reference=None)
        assert terminal.pk is not None
        assert terminal.customer_reference is None

    def test_save_succeeds_with_null_party_id(self):
        terminal = TerminalFactory(party_id=None)
        assert terminal.pk is not None
        assert terminal.party_id is None
