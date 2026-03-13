import pytest
from django.core.exceptions import ValidationError

from ocpi22.payments.validators import (
    validate_ci_ascii_string,
    validate_currency_code,
    validate_eft_data,
    validate_terminal_party_identification,
    validate_total_costs,
)


class TestValidateCiAsciiString:
    @pytest.mark.parametrize(
        "value",
        [
            "hello",
            "ABC123",
            "valid-ascii_string.ok",
            "",
        ],
    )
    def test_validate_ci_ascii_string_passes_for_valid_ascii(self, value):
        validate_ci_ascii_string(value)

    @pytest.mark.parametrize(
        "value",
        [
            "caf\u00e9",
            "\u20ac10.00",
            "na\u00efve",
        ],
    )
    def test_validate_ci_ascii_string_raises_for_non_ascii_characters(self, value):
        with pytest.raises(ValidationError) as exc_info:
            validate_ci_ascii_string(value)

        assert exc_info.value.code == "invalid_ascii"


class TestValidateCurrencyCode:
    @pytest.mark.parametrize(
        "value",
        [
            "EUR",
            "USD",
            "GBP",
            "NOK",
            "SEK",
            "CHF",
        ],
    )
    def test_validate_currency_code_passes_for_valid_iso_4217_codes(self, value):
        validate_currency_code(value)

    @pytest.mark.parametrize(
        "value",
        [
            "XYZ",
            "AAA",
            "123",
            "EU",
            "EURO",
        ],
    )
    def test_validate_currency_code_raises_for_invalid_codes(self, value):
        with pytest.raises(ValidationError) as exc_info:
            validate_currency_code(value)

        assert exc_info.value.code == "invalid_currency_code"


class TestValidateEftData:
    def test_validate_eft_data_passes_for_valid_list_of_ascii_strings(self):
        validate_eft_data(["Mastercard", "AID: 1234", "SEQ: 00"])

    def test_validate_eft_data_raises_for_non_list_input(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_eft_data("not-a-list")

        assert exc_info.value.code == "invalid_eft_data_type"

    def test_validate_eft_data_raises_for_empty_list(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_eft_data([])

        assert exc_info.value.code == "empty_eft_data"

    @pytest.mark.parametrize(
        "value",
        [
            [123],
            [None],
            ["valid", 99],
        ],
    )
    def test_validate_eft_data_raises_for_list_containing_non_string_items(self, value):
        with pytest.raises(ValidationError) as exc_info:
            validate_eft_data(value)

        assert exc_info.value.code == "invalid_eft_data_item_type"

    def test_validate_eft_data_raises_for_list_containing_non_ascii_string(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_eft_data(["valid", "caf\u00e9"])

        assert exc_info.value.code == "invalid_ascii"


class TestValidateTotalCosts:
    def test_validate_total_costs_passes_for_valid_excl_vat_only(self):
        validate_total_costs(10.00, None)

    def test_validate_total_costs_passes_for_valid_excl_and_incl_vat(self):
        validate_total_costs(10.00, 12.10)

    def test_validate_total_costs_passes_when_excl_and_incl_vat_are_equal(self):
        validate_total_costs(10.00, 10.00)

    def test_validate_total_costs_passes_for_zero_costs(self):
        validate_total_costs(0.00, 0.00)

    def test_validate_total_costs_raises_when_excl_vat_is_negative(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_total_costs(-1.00, None)

        assert "total_cost_excl_vat" in exc_info.value.message_dict

    def test_validate_total_costs_raises_when_incl_vat_is_negative(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_total_costs(10.00, -1.00)

        assert "total_cost_incl_vat" in exc_info.value.message_dict
        assert "negative" in exc_info.value.message_dict["total_cost_incl_vat"][0]

    def test_validate_total_costs_raises_when_incl_vat_is_less_than_excl_vat(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_total_costs(10.00, 9.00)

        assert "total_cost_incl_vat" in exc_info.value.message_dict
        assert "less than" in exc_info.value.message_dict["total_cost_incl_vat"][0]


class TestValidateTerminalPartyIdentification:
    @pytest.mark.parametrize(
        "customer_reference, country_code, party_id",
        [
            ("CUST-001", None, None),
            (None, "FI", "CPO"),
            ("CUST-001", "FI", "CPO"),
            ("CUST-001", "FI", None),
            ("CUST-001", None, "CPO"),
        ],
    )
    def test_validate_terminal_party_identification_passes_for_valid_combinations(
        self, customer_reference, country_code, party_id
    ):
        validate_terminal_party_identification(
            customer_reference, country_code, party_id
        )

    def test_validate_terminal_party_identification_raises_when_no_identification_provided(
        self,
    ):
        with pytest.raises(ValidationError) as exc_info:
            validate_terminal_party_identification(None, None, None)

        assert exc_info.value.code == "missing_party_identification"

    def test_validate_terminal_party_identification_raises_when_empty_customer_reference_and_no_pair(
        self,
    ):
        with pytest.raises(ValidationError) as exc_info:
            validate_terminal_party_identification("", None, None)

        assert exc_info.value.code == "missing_party_identification"

    def test_validate_terminal_party_identification_raises_when_country_code_provided_without_party_id(
        self,
    ):
        with pytest.raises(ValidationError) as exc_info:
            validate_terminal_party_identification(None, "FI", None)

        assert exc_info.value.code == "incomplete_party_identification"

    def test_validate_terminal_party_identification_raises_when_party_id_provided_without_country_code(
        self,
    ):
        with pytest.raises(ValidationError) as exc_info:
            validate_terminal_party_identification(None, None, "CPO")

        assert exc_info.value.code == "incomplete_party_identification"

    @pytest.mark.parametrize(
        "country_code, party_id",
        [
            ("FI", None),
            (None, "CPO"),
        ],
    )
    def test_validate_terminal_party_identification_raises_when_partial_pair_and_empty_customer_reference(
        self, country_code, party_id
    ):
        with pytest.raises(ValidationError) as exc_info:
            validate_terminal_party_identification("", country_code, party_id)

        assert exc_info.value.code == "incomplete_party_identification"

    def test_validate_terminal_party_identification_passes_when_customer_reference_matches_expected(
        self,
    ):
        validate_terminal_party_identification(
            "CUST-001", None, None, ptp_customer_reference="CUST-001"
        )

    def test_validate_terminal_party_identification_passes_when_no_expected_customer_reference_configured(
        self,
    ):
        validate_terminal_party_identification(
            "ANY-VALUE", None, None, ptp_customer_reference=None
        )

    def test_validate_terminal_party_identification_raises_when_customer_reference_does_not_match_expected(
        self,
    ):
        with pytest.raises(ValidationError) as exc_info:
            validate_terminal_party_identification(
                "WRONG-REF", None, None, ptp_customer_reference="CUST-001"
            )

        assert exc_info.value.code == "invalid_customer_reference"

    def test_validate_terminal_party_identification_raises_when_customer_reference_is_case_different_from_expected(
        self,
    ):
        with pytest.raises(ValidationError) as exc_info:
            validate_terminal_party_identification(
                "cust-001", None, None, ptp_customer_reference="CUST-001"
            )

        assert exc_info.value.code == "invalid_customer_reference"
