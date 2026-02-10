from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from generic.countries import COUNTRIES_ISO_2_SET, COUNTRIES_ISO_3_SET


def validate_country_code_alpha2(value: str) -> None:
    """Validate that the value is a valid ISO 3166-1 alpha-2 country code."""
    if value.upper() not in COUNTRIES_ISO_2_SET:
        raise ValidationError(
            _("'%(value)s' is not a valid ISO 3166-1 alpha-2 country code."),
            code="invalid_country_code_alpha2",
            params={"value": value},
        )


def validate_country_code_alpha3(value: str) -> None:
    """Validate that the value is a valid ISO 3166-1 alpha-3 country code."""
    if value.upper() not in COUNTRIES_ISO_3_SET:
        raise ValidationError(
            _("'%(value)s' is not a valid ISO 3166-1 alpha-3 country code."),
            code="invalid_country_code_alpha3",
            params={"value": value},
        )
