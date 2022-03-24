import secrets
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional, Any

from django.conf import settings
from django.core.validators import RegexValidator
from rest_framework import serializers, status
from rest_framework.renderers import BrowsableAPIRenderer

from ocpi22.ocpi_util import OCPIResponse
from ocpiconnector.ocpi_identities import ocpi_identities, OCPIIdentities, Party


def clear_empty(dict_with_possibly_empty_values):
    """
    Do a recursive cleanup for a dict and remove empty values and dicts with no keys

    # Must leave zero floats untouched
    >>> clear_empty(dict(jotain=0.0))
    OrderedDict([('jotain', 0.0)])

    # Must remove empty dictionaries recursively
    >>> clear_empty(dict(jotain='', muuta=dict(jotain='')))
    OrderedDict()
    """

    if not isinstance(dict_with_possibly_empty_values, dict):
        return dict_with_possibly_empty_values
    result = OrderedDict()
    for key, value in dict_with_possibly_empty_values.items():
        value = clear_empty(value)
        if value or value == 0.0:
            result[key] = value
    return result


def get_total_cost(obj):
    return clear_empty(dict(
        excl_vat=obj.total_cost_excl_vat,
        incl_vat=obj.total_cost_incl_vat
    ))


def hours_minutes(hours_float: float) -> str:
    """
    >>> hours_minutes(1.5)
    '1h 30min'
    >>> hours_minutes(2)
    '2h'
    >>> hours_minutes(.5)
    '30min'
    >>> hours_minutes(2/3600)
    '2 seconds'
    """

    hours = int(hours_float)
    minutes = int((hours_float - hours) * 60)
    if hours:
        if minutes:
            return f'{hours}h {minutes}min'
        else:
            return f'{hours}h'
    elif not hours and not minutes:
        seconds = int(hours_float * 3600)
        return f'{seconds} seconds'
    else:
        return f'{minutes}min'


def generate_random_token() -> str:
    """
    >>> len(generate_random_token())
    64
    >>> generate_random_token() != generate_random_token()
    True
    """
    return secrets.token_hex(32)


class SerializerCleanedUp(serializers.Serializer):
    def to_representation(self, value):
        # Remove empty values
        repr_dict = super().to_representation(value)
        result = clear_empty(repr_dict)
        return result


class HyperlinkedModelSerializerCleanedUp(serializers.HyperlinkedModelSerializer):
    def to_representation(self, value):
        # Remove empty values
        repr_dict = super().to_representation(value)
        result = clear_empty(repr_dict)
        return result

    def get_detail_url(self, obj) -> str:
        """
        Construct a URL which points to the object instance view
        :param obj: The object we need the instance view for
        :return: The URL string to the instance view
        """
        request = self.context.get("request")
        if not hasattr(obj, 'get_absolute_url') or not request:
            return ''
        return f'{request.build_absolute_uri(obj.get_absolute_url())}'

    def get_url(self, obj) -> str:
        """
        Construct a URL which points to the object instance view
        :param obj: The object we need the instance view for
        :return: The URL string to the instance view
        """
        request = self.context.get("request")
        if not hasattr(obj, 'get_cpo_url') or not request:
            return ''
        return f'{request.build_absolute_uri(obj.get_cpo_url())}'

    def get_quick_url(self, obj) -> str:
        """
        Construct a URL which points to the object instance view
        :param obj: The object we need the instance view for
        :return: The URL string to the instance view
        """
        request = self.context.get("request")
        if not hasattr(obj, 'get_quick_url') or not request:
            return ''
        return f'{request.build_absolute_uri(obj.get_quick_url())}'

    def get_status_url(self, obj) -> str:
        """
        Construct a URL which points to the object instance view
        :param obj: The object we need the instance view for
        :return: The URL string to the instance view
        """
        request = self.context.get("request")
        if not hasattr(obj, 'get_status_url') or not request:
            return ''
        return f'{request.build_absolute_uri(obj.get_status_url())}'

    detail_url = serializers.SerializerMethodField(
        read_only=True,
        help_text='This non-OCPI field exists for educational purposes'
    )
    url = serializers.SerializerMethodField(read_only=True)
    quick_url = serializers.SerializerMethodField(
        read_only=True,
        help_text='This non-OCPI field exists for educational purposes'
    )
    status_url = serializers.SerializerMethodField(
        read_only=True,
        help_text='This non-OCPI field exists for educational purposes'
    )


class UpperCaseSerializerField(serializers.CharField):

    def __init__(self, *_args, **kwargs):
        super(UpperCaseSerializerField, self).__init__(**kwargs)

    def to_representation(self, value):
        value = super(UpperCaseSerializerField, self).to_representation(value)
        if value:
            return value.upper()


def check_ownership(request, country_code, party_id, check_operator_id_from_request_data=True):
    if not hasattr(request, 'credentials'):
        return False
    # ic(request.credentials.roles.filter(role='HUB'))
    if request.credentials.roles.filter(role='HUB').count():
        # We trust hubs
        return True
    if check_operator_id_from_request_data and hasattr(request, 'data'):
        cc = request.data.get('country_code')
        pi = request.data.get('party_id')
        if (cc and cc != country_code) or (pi and pi != party_id):
            return False
    for role in request.credentials.roles.all():
        if role.country_code == country_code and role.party_id == party_id:
            return True
    return False


def matching_operator(request, country_code, party_id) -> bool:
    if request.user.is_staff:
        return True
    if not hasattr(request, 'credentials'):
        return False
    # ic(request.credentials.roles.filter(role='HUB'))
    if request.credentials.roles.filter(role='HUB').count():
        # We trust hubs
        return True
    for r in request.credentials.roles.all():
        if r.country_code == country_code and r.party_id == party_id:
            return True
    return False


CURRENCY_CHOICES = (
    ('EUR', 'Euro'),
    ('ALL', 'Albanian lek'),
    ('BYN', 'Belarusian ruble'),
    ('BAM', 'Bosnia and Herzegovina convertible mark'),
    ('BGN', 'Bulgarian lev'),
    ('HRK', 'Croatian kuna'),
    ('CZK', 'Czech koruna'),
    ('DKK', 'Danish krone'),
    ('ISK', 'Icelandic króna'),
    ('HUF', 'Hungarian forint'),
    ('MDL', 'Moldovan leu'),
    ('NOK', 'Norwegian krone'),
    ('PLN', 'Polish złoty'),
    ('GBP', 'Pound sterling'),
    ('RON', 'Romanian leu'),
    ('RUB', 'Russian ruble'),
    ('MKD', 'Second Macedonian denar'),
    ('RSD', 'Serbian dinar'),
    ('SEK', 'Swedish krona'),
    ('CHF', 'Swiss franc'),
    ('TRY', 'Turkish lira'),
    ('UAH', 'Ukrainian hryvnia'),
)


def apply_min_and_max(value: Any, minimum: Any, maximum: Any) -> Any:
    """
    >>> apply_min_and_max(10, 3, 9)
    9
    >>> apply_min_and_max(2, 3, 9)
    3
    """
    minimum = minimum or -99999999
    maximum = maximum or 99999999
    return max(minimum, min(maximum, value))


def apply_step_size(value, step_size, divisor=1) -> float:
    """
    >>> apply_step_size(26/60, 60*15, 3600)  # 26 minutes, 15 minute step, seconds/hour
    0.5
    >>> apply_step_size(16/60, 60*15, 3600)  # 16 minutes, 15 minute step, seconds/hour
    0.5
    >>> apply_step_size(3, 2)  # 3 kWh, round up to 2 kWh, 1-to-1 comparison
    4.0
    >>> apply_step_size(5.1, 5)  # 5.1 kWh, round up to 5 kWh, 1-to-1 comparison
    10.0
    >>> apply_step_size(5.1, .5)  # 5.1 kWh, round up to 0.5 kWh, 1-to-1 comparison
    5.5
    >>> apply_step_size(2.5, 60, 3600)  # 2h 30min, 1 minute step, seconds/hour
    2.5

    @param value:
    @param step_size:
    @param divisor: If value and step_size have different units, such as value in hours and step_size in seconds, \
                    convert hours into seconds by using divisor=3600
    @return:
    """
    assert value > 0 and step_size > 0 and divisor > 0, 'apply_step_size() requires positive parameters'
    value = value * divisor
    modulo = (value % step_size)
    if modulo:
        value += step_size - modulo
    return value / divisor


def pretty_currency(c):
    """
    Apply a currency symbol if such is known
    >>> pretty_currency('EUR')
    '€'
    >>> pretty_currency('PLN')
    'zł'
    """
    return dict(EUR='€', GBP='£', USD='$', PLN='zł').get(c, c)


def format_currency(number: Optional[float], currency: Optional[str]) -> str:
    """
    >>> format_currency(1.1, 'EUR')
    '1,10€'
    >>> format_currency(1.12, 'EUR')
    '1,12€'
    >>> format_currency(1.123, 'EUR')
    '1,12€'
    >>> format_currency(1.0, 'EUR')
    '1€'
    >>> format_currency(None, 'EUR')
    '-'
    >>> format_currency(1.0, None)
    '1'
    """

    if number is None:
        return '-'
    currency = pretty_currency(currency or '')
    if float(int(number)) == number:
        result = f"{number:.0f}{currency or ''}"
    else:
        result = f"{number:.2f}{currency or ''}"
    return result.replace(".", settings.DECIMAL_SEPARATOR)


def format_cost(incl_vat: float, excl_vat: float, currency: str) -> str:
    """
    Format a string which hides zero values and shows the price with and without tax, if available
    >>> format_cost(1.2, 1.0, "EUR")
    '1,20€'
    >>> format_cost(1.2, 0.0, "EUR")
    '1,20€'
    >>> format_cost(0.0, 1.0, "EUR")
    '1€ (excl.VAT)'
    >>> format_cost(0.0, 0.0, "EUR")
    '-'
    """

    cost_format = "{excl_vat} (excl.VAT)"
    if not excl_vat and not incl_vat:
        return '-'
    if incl_vat:
        cost_format = "{incl_vat}"

    return cost_format.format(
        incl_vat=format_currency(incl_vat, currency),
        excl_vat=format_currency(excl_vat, currency)
    )


def calculate_partition(coordinate):
    if not coordinate:
        return 0
    return int(float(coordinate) * 100.0)


# def _get_identities_list(source: dict=os.environ) -> [str]:
#     """
#     Get the country_codes and party_ids for different roles of this Platform
#
#     >>> _get_identities_list(source=dict(CPO='FI*CPO', EMSP='FI*MSP'))
#     ['FI*CPO', 'FI*MSP']
#
#     @param source: For testing purposes
#     @return: List of identity strings
#     """
#     return list(filter(None, [source.get(i) for i in role_options if source.get(i)]))

@lru_cache(maxsize=None)
def is_our_identifier(party: Party, identities=None) -> bool:
    """
    Check if the given country_code and party_id match one of our identities
    >>> identities = OCPIIdentities(source=dict(CPO='FI*CPO', EMSP='FI*MSP'))
    >>> is_our_identifier(Party('FI', 'MSP'), identities=identities)
    True
    >>> is_our_identifier(Party('', 'MSP'), identities=identities)
    False
    >>> is_our_identifier(Party('', ''), identities=identities)
    False

    """
    if not party.country_code or not party.party_id:
        return False
    if identities is None:
        identities = ocpi_identities
    # ic(str(party), identities)
    result = bool(str(party) in identities)
    return result


class ModelUtilMixin:
    @classmethod
    def get_if_exists(cls, *args, **kwargs) -> any:
        # noinspection PyUnresolvedReferences
        objects = cls.objects.filter(*args, **kwargs)
        if objects.count():
            return objects.first()
        return None

    def party(self) -> str:
        if hasattr(self, 'location'):
            return f'{self.location.country_code}*{self.location.party_id}'
        if hasattr(self, 'country_code') and hasattr(self, 'party_id'):
            return f'{self.country_code}*{self.party_id}'
        return ''

    def get_party(self):
        if hasattr(self, 'location'):
            return Party(self.location.country_code, self.location.party_id)
        if hasattr(self, 'country_code') and hasattr(self, 'party_id'):
            return Party(self.country_code, self.party_id)
        raise NotImplementedError(f'Object type {self.__class__} has no country_code and party_id')

    def object_owner(self) -> str:
        # For admin UI
        return self.party()

    def is_ours(self) -> bool:
        # Returns true if we hold the master data for this object
        if not (hasattr(self, 'country_code') and hasattr(self, 'party_id')):
            return False
        return bool(is_our_identifier(self.get_party()))

    def is_owner(self, request) -> bool:
        if request.user.is_superuser:
            return True
        if not hasattr(self, 'country_code') or not hasattr(self, 'party_id'):
            return False
        return check_ownership(request, self.country_code, self.party_id)

    def change_fields_to_upper_case(self) -> None:
        if hasattr(self, 'upper_case_fields'):
            for field in self.upper_case_fields:
                f = self.__getattribute__(field)
                if f and isinstance(f, str):
                    upper_value = f.upper()
                    self.__setattr__(field, upper_value)


PREMIUM_MESSAGE = 'This feature is available in the OCPI Connector Premium. ' \
                  'You can upgrade at http://ocpi.guide/compare/'
PREMIUM_RESPONSE = OCPIResponse(
    status_message=PREMIUM_MESSAGE,
    status_code=2999, http_status=status.HTTP_426_UPGRADE_REQUIRED
)


class TimePeriod:
    seconds = 0
    start = None
    end = None

    def __init__(self,
                 session_start: datetime,
                 session_end: datetime,
                 tariff_start: datetime,
                 tariff_end: datetime):
        """
        Calculate how many seconds two time periods are overlapping. Used for calculating how much of the
        charging session is within each type of Tariff time period

        @return: How many Seconds of this session is within this Tariff

        >>> dt = datetime(2000, 1, 1, 0, 0)
        >>> TimePeriod(dt, dt + timedelta(seconds=2*60), dt + timedelta(seconds=60), dt + timedelta(seconds=3*60), )
        2000-01-01 00:01:00 - 2000-01-01 00:02:00, 60
        >>> TimePeriod(dt, dt + timedelta(seconds=2*60), dt - timedelta(seconds=10*60), dt + timedelta(seconds=1*60), )
        2000-01-01 00:00:00 - 2000-01-01 00:01:00, 60
        >>> TimePeriod(dt, dt + timedelta(seconds=2*60), dt + timedelta(seconds=2*60), dt + timedelta(seconds=3*60), )
        -
        >>> TimePeriod(dt, dt + timedelta(seconds=2*60), dt - timedelta(seconds=2*60), dt - timedelta(seconds=60), )
        -
        """

        self.seconds = int(max(min(session_end - tariff_start, tariff_end - session_start).total_seconds(), 0))
        if self.seconds:
            self.start = max(session_start, tariff_start)
            self.end = min(session_end, tariff_end)

    def __str__(self):
        if not self.seconds:
            return '-'
        return f'{self.start} - {self.end}, {self.seconds}'

    def __int__(self):
        return self.seconds

    def __bool__(self):
        return bool(self.seconds)

    def __repr__(self):
        return self.__str__()


uid_validator = RegexValidator(r'^[0-9a-zA-Z\*\-]+$', message='Numbers and letters only')


class OnlyRawBrowsableAPIRenderer(BrowsableAPIRenderer):
    def render_form_for_serializer(self, serializer):
        return ""


@dataclass
class MyCommandResponse:
    success: bool
    message: str
