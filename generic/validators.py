from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from generic.countries import COUNTRIES_ISO_2_SET, COUNTRIES_ISO_3_SET


def validate_country_code_alpha2(value: str) -> None:
    if value.upper() not in COUNTRIES_ISO_2_SET:
        raise ValidationError(
            _("'%(value)s' is not a valid ISO 3166-1 alpha-2 country code."),
            code="invalid_country_code_alpha2",
            params={"value": value},
        )


def validate_country_code_alpha3(value: str) -> None:
    if value.upper() not in COUNTRIES_ISO_3_SET:
        raise ValidationError(
            _("'%(value)s' is not a valid ISO 3166-1 alpha-3 country code."),
            code="invalid_country_code_alpha3",
            params={"value": value},
        )


def validate_latitude(value: str) -> None:
    try:
        lat = float(value)
    except (ValueError, TypeError):
        raise ValidationError(
            _("'%(value)s' is not a valid latitude. Must be a decimal number."),
            code="invalid_latitude",
            params={"value": value},
        )
    if not (-90 <= lat <= 90):
        raise ValidationError(
            _("'%(value)s' is not a valid latitude. Must be between -90 and 90."),
            code="invalid_latitude_range",
            params={"value": value},
        )


def validate_longitude(value: str) -> None:
    try:
        lng = float(value)
    except (ValueError, TypeError):
        raise ValidationError(
            _("'%(value)s' is not a valid longitude. Must be a decimal number."),
            code="invalid_longitude",
            params={"value": value},
        )
    if not (-180 <= lng <= 180):
        raise ValidationError(
            _("'%(value)s' is not a valid longitude. Must be between -180 and 180."),
            code="invalid_longitude_range",
            params={"value": value},
        )
