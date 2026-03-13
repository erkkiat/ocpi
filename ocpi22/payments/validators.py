from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from ocpi22.util import VALID_CURRENCY_CODE_SET


def validate_ci_ascii_string(value: str, field_name: str = "field") -> None:
    if not value:
        return

    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        raise ValidationError(
            _("'%(field)s' must contain only ASCII characters. Got: %(value)s"),
            code="invalid_ascii",
            params={"field": field_name, "value": value},
        )


def validate_currency_code(value: str) -> None:
    if value.upper() not in VALID_CURRENCY_CODE_SET:
        raise ValidationError(
            _("'%(value)s' is not a valid ISO 4217 currency code."),
            code="invalid_currency_code",
            params={"value": value},
        )


def validate_eft_data(value: list) -> None:
    if not isinstance(value, list):
        raise ValidationError(
            _("EFT data must be a list of strings."),
            code="invalid_eft_data_type",
        )

    if len(value) == 0:
        raise ValidationError(
            _("EFT data must contain at least one item."),
            code="empty_eft_data",
        )

    for idx, item in enumerate(value):
        if not isinstance(item, str):
            raise ValidationError(
                _(
                    "All items in EFT data must be strings. "
                    "Item at index %(index)s is %(type)s."
                ),
                code="invalid_eft_data_item_type",
                params={"index": idx, "type": type(item).__name__},
            )

        validate_ci_ascii_string(item, f"EFT data item at index {idx}")


def validate_terminal_party_identification(
    customer_reference: str | None,
    country_code: str | None,
    party_id: str | None,
    ptp_customer_reference: str | None = None,
) -> None:
    if customer_reference:
        if ptp_customer_reference and customer_reference != ptp_customer_reference:
            raise ValidationError(
                _(
                    "customer_reference '%(received)s' does not match the configured value."
                ),
                code="invalid_customer_reference",
                params={"received": customer_reference},
            )
        return

    if bool(country_code) != bool(party_id):
        raise ValidationError(
            _(
                "country_code and party_id must both be provided together or both omitted."
            ),
            code="incomplete_party_identification",
        )

    if not country_code and not party_id:
        raise ValidationError(
            _(
                "A Terminal must have either a customer_reference "
                "or both country_code and party_id."
            ),
            code="missing_party_identification",
        )


def validate_total_costs(excl_vat: float, incl_vat: float | None) -> None:
    if excl_vat < 0:
        raise ValidationError(
            {"total_cost_excl_vat": _("Total cost excluding VAT cannot be negative.")},
            code="negative_total_cost_excl_vat",
        )

    if incl_vat is not None:
        if incl_vat < 0:
            raise ValidationError(
                {
                    "total_cost_incl_vat": _(
                        "Total cost including VAT cannot be negative."
                    )
                },
                code="negative_total_cost_incl_vat",
            )

        if incl_vat < excl_vat:
            raise ValidationError(
                {
                    "total_cost_incl_vat": _(
                        "Total cost including VAT (%(incl)s) cannot be less than "
                        "total cost excluding VAT (%(excl)s)."
                    )
                },
                code="invalid_vat_relationship",
                params={"incl": incl_vat, "excl": excl_vat},
            )
