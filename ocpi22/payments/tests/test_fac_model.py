import pytest
from django.core.exceptions import ValidationError

from ocpi22.tests.factories import FinancialAdviceConfirmationFactory


@pytest.mark.django_db
class TestFACValidators:
    @pytest.mark.parametrize("value", ["caf\u00e9", "\u20ac10", "na\u00efve"])
    def test_save_raises_validation_error_when_fac_id_contains_non_ascii(self, value):
        with pytest.raises(ValidationError, match="must contain only ASCII"):
            FinancialAdviceConfirmationFactory(fac_id=value)

    @pytest.mark.parametrize("value", ["caf\u00e9", "\u20ac10", "na\u00efve"])
    def test_save_raises_validation_error_when_authorization_reference_contains_non_ascii(
        self, value
    ):
        with pytest.raises(ValidationError, match="must contain only ASCII"):
            FinancialAdviceConfirmationFactory(authorization_reference=value)

    @pytest.mark.parametrize("value", ["caf\u00e9", "\u20ac10", "na\u00efve"])
    def test_save_raises_validation_error_when_capture_status_message_contains_non_ascii(
        self, value
    ):
        with pytest.raises(ValidationError, match="must contain only ASCII"):
            FinancialAdviceConfirmationFactory(capture_status_message=value)

    def test_save_succeeds_with_null_capture_status_message(self):
        fac = FinancialAdviceConfirmationFactory(capture_status_message=None)
        assert fac.pk is not None
        assert fac.capture_status_message is None

    def test_save_raises_validation_error_when_eft_data_is_empty(self):
        with pytest.raises(ValidationError, match="must contain at least one item"):
            FinancialAdviceConfirmationFactory(eft_data=[])

    @pytest.mark.parametrize("value", ["caf\u00e9", "\u20ac10"])
    def test_save_raises_validation_error_when_eft_data_item_contains_non_ascii(
        self, value
    ):
        with pytest.raises(ValidationError, match="must contain only ASCII"):
            FinancialAdviceConfirmationFactory(eft_data=[value])

    def test_save_raises_validation_error_when_excl_vat_is_negative(self):
        with pytest.raises(ValidationError, match="cannot be negative"):
            FinancialAdviceConfirmationFactory(total_cost_excl_vat=-1.0)

    def test_save_raises_validation_error_when_incl_vat_is_less_than_excl_vat(self):
        with pytest.raises(ValidationError, match="less than"):
            FinancialAdviceConfirmationFactory(
                total_cost_excl_vat=10.0, total_cost_incl_vat=9.0
            )

    def test_save_raises_validation_error_with_invalid_currency_code(self):
        with pytest.raises(ValidationError, match="is not a valid ISO 4217"):
            FinancialAdviceConfirmationFactory(currency="XYZ")

    @pytest.mark.parametrize(
        "capture_status_code", ["SUCCESS", "PARTIAL_SUCCESS", "FAILED"]
    )
    def test_save_succeeds_with_all_valid_capture_status_codes(
        self, capture_status_code
    ):
        fac = FinancialAdviceConfirmationFactory(
            capture_status_code=capture_status_code
        )
        assert fac.pk is not None
        assert fac.capture_status_code == capture_status_code
