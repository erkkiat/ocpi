import pytest
from django.core.exceptions import ValidationError

from ocpi22.tests.factories import TerminalFactory


@pytest.mark.django_db
class TestTerminalCountryCodeValidationOnSave:
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


@pytest.mark.django_db
class TestTerminalCountryValidationOnSave:
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


@pytest.mark.django_db
class TestTerminalCountryValidationOnUpdate:
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
