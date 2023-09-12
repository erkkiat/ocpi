import base64
import csv
import hashlib
import json
import secrets
import urllib.parse
from collections import OrderedDict
from dataclasses import dataclass, field, asdict, is_dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional, Any, Union

from django.utils.translation import gettext as _

import cachetools
import pycountry
import redis
from django.conf import settings
from django.core.validators import RegexValidator
from django.utils.module_loading import import_string
from geopy import Nominatim
from requests import Response
from rest_framework import serializers, versioning
from rest_framework.exceptions import ValidationError
from rest_framework.metadata import SimpleMetadata
from rest_framework.pagination import PageNumberPagination
from rest_framework.renderers import BrowsableAPIRenderer
from urllib3.util import Url

from ocpi22 import choices
from ocpi22.choices import OcpiModuleEnum, EndpointRoleEnum, OcpiRolesEnum
from ocpi22.ocpi.util import OCPIResponse
from ocpi22.routing import find_route
from ocpi22.tasks import send_ocpi_request
from ocpiconnector.ocpi_identities import ocpi_identities, OCPIIdentities, Party, get_our_party
from util import format_url


# slack_logging.init()


def clear_empty(dict_with_possibly_empty_values: dict) -> Union[OrderedDict, dict]:
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
        if value or value == 0.0 or value == 0:
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
    '1 h 30 min'
    >>> hours_minutes(2)
    '2 h'
    >>> hours_minutes(.5)
    '30 min'
    >>> hours_minutes(2/3600)
    '2 s'
    """

    hours = int(hours_float)
    minutes = int((hours_float - hours) * 60)
    if hours:
        if minutes:
            return f'{hours} h {minutes} min'
        else:
            return f'{hours} h'
    elif not hours and not minutes:
        seconds = int(hours_float * 3600)
        return f'{seconds} s'
    else:
        return f'{minutes} min'


def generate_random_token(length: int = 32) -> str:
    """
    >>> len(generate_random_token())
    32
    >>> generate_random_token() != generate_random_token()
    True
    """
    return secrets.token_hex(int(length/2))


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
    if not hasattr(request, 'credentials'):
        return False
    # We trust staff and hubs implicitly
    return request.user.is_staff or request.credentials.is_hub \
        or bool(request.credentials.roles.filter(country_code__iexact=country_code, party_id__iexact=party_id))


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
    ('PHP', 'Philippine peso'),
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
    >>> apply_step_size(3, 2000, 1000)  # 3 kWh, round up to 2 kWh, 1-to-1 comparison
    4.0
    >>> apply_step_size(5.1, 5000, 1000)  # 5.1 kWh, round up to 5 kWh, 1-to-1 comparison
    10.0
    >>> apply_step_size(5.1, 500, 1000)  # 5.1 kWh, round up to 0.5 kWh, 1-to-1 comparison
    5.5
    >>> apply_step_size(2.5, 60, 3600)  # 2h 30min, 1 minute step, seconds/hour
    2.5
    >>> apply_step_size(2.5, 0, 3600)  # Failsafe should take care of this
    2.5
    >>> apply_step_size(0.1155, 1, 1000)  # Failsafe should take care of this
    0.116

    @param value:
    @param step_size:
    @param divisor: If value and step_size have different units, such as value in hours and step_size in seconds, \
                    convert hours into seconds by using divisor=3600
    @return:
    """
    # Step size has to be at least 1
    step_size = max(step_size, 1)
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
    return dict(EUR='€', GBP='£', USD='$', PLN='zł', ALL='L', PHP='₱').get(c, c)


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
    >>> format_currency(1.0, 'PHP')
    '₱1'
    >>> format_currency(None, 'EUR')
    '-'
    >>> format_currency(1.0, None)
    '1'
    """

    if number is None:
        return '-'
    currency = pretty_currency(currency or '')
    if float(int(number)) == number:
        number_str = str(int(number))
    else:
        number_str = f"{number:.2f}"
    if currency in {'$', '₱'}:
        result = f"{currency}{number_str}"
    else:
        result = f"{number_str}{currency}"
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
    >>> test_identities = OCPIIdentities(source=dict(CPO='FI*CPO', EMSP='FI*MSP'))
    >>> is_our_identifier(Party('FI', 'MSP'), identities=test_identities)
    True
    >>> is_our_identifier(Party('', 'MSP'), identities=test_identities)
    False
    >>> is_our_identifier(Party('', ''), identities=test_identities)
    False

    """
    assert isinstance(party, Party), f'is_our_identifier() requires a Party object, not {type(party)}'
    if not party.country_code or not party.party_id:
        return False
    if identities is None:
        identities = ocpi_identities
    # ic(str(party), identities)
    result = bool(str(party) in identities)
    return result


class ModelUtilMixin:
    @classmethod
    def get_if_exists(cls, *args, raise_exception=False, **kwargs) -> any:
        # Is the object already fetched?
        uid = kwargs.get('uid')
        if isinstance(uid, cls):
            return uid

        objects = cls.objects.filter(*args, **kwargs)
        if objects.count() > 1:
            raise ValidationError(f'There are more than one {cls.__name__} with the criteria {kwargs} in the database')
        if objects.count() == 1:
            return objects.first()
        if raise_exception:
            error_message = f"{cls.__name__} with UID " \
                            f"{kwargs.get('uid', 'N/A')} doesn't exist in the database"
            raise cls.DoesNotExist(error_message)
        return None

    def party(self) -> str:  # Todo: rename to party_str, but be careful
        """
        >>> from ocpi22.models.location import Location
        >>> Location(country_code='FI', party_id='CPO').party()
        'FI*CPO'
        """
        if hasattr(self, 'ocpi_master') and self.ocpi_master:
            return f'{self.ocpi_master.country_code}*{self.ocpi_master.party_id}'
        if hasattr(self, 'location') and self.location:
            return f'{self.location.country_code}*{self.location.party_id}'
        if hasattr(self, 'country_code') and hasattr(self, 'party_id'):
            return f'{self.country_code}*{self.party_id}'
        return ''
    party.short_description = _('Data Owner')

    def party_long(self) -> str:
        if hasattr(self, 'ocpi_master') and self.ocpi_master:
            return f'{self.ocpi_master.business_details.name}' \
                f' ({self.ocpi_master.country_code}*{self.ocpi_master.party_id})'
        return self.party()
    party_long.short_description = _('Data Owner')

    def get_party(self) -> Party:
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

    def get_serializer(self, request=None, version=None):
        assert request or version, 'get_serializer() requires either request or version'
        version = version or request.version
        serializer_class = self.get_serializer_class(version)
        return serializer_class(self, context={'request': request, 'version': version})

    # @abc.abstractmethod
    # def get_serializer_class(self, version):
    #     ...


class ParseUrl:
    """
    >>> a = ParseUrl('https://chargerhub:Electro3333!@87.246.28.135:1880/start_transaction/{evse_id}/?a=1&b=2')
    >>> a.url, a.username, a.password, a.port
    ('https://87.246.28.135:1880/start_transaction/{evse_id}/?a=1&b=2', 'chargerhub', 'Electro3333!', 1880)
    >>> a = ParseUrl('https://chargerhub:Electro3333!@87.246.28.135/start_transaction/{evse_id}/?a=1&b=2')
    >>> a.url, a.username, a.password, a.port
    ('https://87.246.28.135/start_transaction/{evse_id}/?a=1&b=2', 'chargerhub', 'Electro3333!', None)
    """
    url = ''
    username = ''
    password = ''
    port = 80

    def __init__(self, url):
        parsed = urllib.parse.urlparse(url)
        self.username = parsed.username
        self.password = parsed.password
        self.port = parsed.port
        new_url = list(parsed)
        if parsed.port:
            new_url[1] = f'{parsed.hostname}:{parsed.port}'
        else:
            new_url[1] = parsed.hostname
        self.url = urllib.parse.urlunparse(new_url)


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

        >>> dt = datetime(2022, 1, 1, 0, 0)
        >>> TimePeriod(dt, dt + timedelta(seconds=2*60), dt + timedelta(seconds=60), dt + timedelta(seconds=3*60), )
        2022-01-01 00:01:00 - 2022-01-01 00:02:00, 60
        >>> TimePeriod(dt, dt + timedelta(seconds=2*60), dt - timedelta(seconds=10*60), dt + timedelta(seconds=1*60), )
        2022-01-01 00:00:00 - 2022-01-01 00:01:00, 60
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


@dataclass(eq=True, frozen=True)
class MyCommandResponse:
    success: bool
    message: str
    response: Response = field(default=None)


redis_store = redis.from_url(settings.REDIS_URL, decode_responses=True)


class RedisStore:
    def __init__(self, namespace=None, expiration=None):
        self.namespace = namespace
        self.expiration = expiration

    def _format_key(self, key):
        if not self.namespace:
            return key
        return f'{self.namespace}-{key}'

    def __setitem__(self, key, value):
        namespace_key = self._format_key(key)
        # ic()
        # ic(key, namespace_key, value, self.expiration)
        if isinstance(value, dict):
            value = json.dumps(value, default=str)  # serializes also dates
        elif is_dataclass(value):
            value = json.dumps(asdict(value), default=str)
        redis_store.set(namespace_key, value, self.expiration)

    def __getitem__(self, item):
        # ic()
        # ic(item)
        namespace_key = self._format_key(item)
        value = redis_store.get(namespace_key)
        if not value:
            raise KeyError(f'No {item} stored for {self.namespace}')
        if "{" in value:
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
        # ic(item, namespace_key, value)
        return value


class MyMetadata(SimpleMetadata):
    def determine_metadata(self, request, view):
        metadata = super().determine_metadata(request, view)
        if hasattr(view, 'get_extra_metadata'):
            metadata.update(view.get_extra_metadata(request))
        if hasattr(view, 'get_return_values_serializer'):
            serializer = view.get_return_values_serializer()
            if serializer:
                metadata.update(
                    dict(return_values=self.get_serializer_info(serializer))
                )
        return metadata


@lru_cache(maxsize=128)
def build_absolute_uri(path) -> str:
    """
    >>> str(build_absolute_uri('my/path'))
    'http://testserver.test/my/path'
    """
    return str(Url(host=settings.HOSTNAME, path=path, scheme=settings.SCHEME))


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


command_store = RedisStore('command-result', expiration=settings.REMOTE_COMMAND_EXPIRATION)


@lru_cache(maxsize=128)
def _format_redis_key(key: str, namespace: str) -> str:
    return f'{namespace}-{key}'


def set_callbacks_parameter(key: str, value: str) -> None:
    redis_store.set(_format_redis_key(key, 'callback'), value)


def get_callbacks_parameter(key: str) -> Union[str, int, list]:
    return redis_store.get(_format_redis_key(key, 'callback'))


def build_callback_request(key: str, data: dict) -> tuple[str, dict]:
    url = get_callbacks_parameter(key)
    parsed = ParseUrl(url)
    user = parsed.username
    password = parsed.password
    if user and password:
        kwargs = dict(auth=(user, password))
    else:
        kwargs = dict()
    url = format_url(parsed.url, **data)
    return url, kwargs


def str_to_deterministic_int(reservation_id, limit=None) -> Optional[int]:
    """
    >>> str_to_deterministic_int('FI*EON*R12345', 10)
    2590367882
    """
    if not reservation_id:
        return None
    hex_id = hashlib.md5(reservation_id.encode()).hexdigest()
    numerical_id = int(hex_id, 16)
    if limit:
        return int(str(numerical_id)[:limit])
    return numerical_id


def base64_to_ascii(s: str) -> str:
    return base64.b64decode(s).decode('ascii')


timezones = dict()


@cachetools.cached(cache=timezones)
def get_timezones():
    result = dict()
    with open('ocpi22/data/timezones.csv') as file:
        data = csv.reader(file, delimiter=';')
        for code, name, timezone in data:
            result[code] = timezone
    return result


def get_time_zone(country_code_2_chars: str) -> str:
    timezone_list = get_timezones()
    return timezone_list.get(country_code_2_chars.upper(), '')


def country_code_from_2_to_3_chars(country_code: str) -> str:
    country = pycountry.countries.get(alpha_2=country_code)
    return country.alpha_3


def fill_out_location_address(data: dict, lat: Union[float, str], lng: Union[float, str]) -> dict:
    language = data.pop('language', False)
    if 'address' in data and 'city' in data and 'country' in data:
        return data
    if not lat or not lng:
        return data
    locator = Nominatim(user_agent="solidroam.com")
    coordinates = f"{lat},{lng}"
    location = locator.reverse(coordinates, language=language)
    address = location.raw.get('address')
    data['address'] = f"{address.get('road') or '-'} {address.get('house_number') or ''}".strip()
    data['city'] = address.get('city') or '-'
    data['postal_code'] = address.get('postcode') or '-'
    country_code_2_chars = address.get('country_code', '')
    data['country'] = country_code_from_2_to_3_chars(country_code_2_chars).upper()

    # Todo: Fill out the time zone based on country code
    data['time_zone'] = get_time_zone(country_code_2_chars)

    return data


class OCPIVersioning(versioning.BaseVersioning):
    default_version = '2.2.1'

    def determine_version(self, request, *args, **kwargs):
        if 'ocpi/2.2/' in request.path:
            return '2.2'
        return '2.2.1'


class OCPIListModelMixin:
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer_class = self.get_serializer_class() \
            if hasattr(self, 'get_serializer_class') else self.serializer_class
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = serializer_class(page, many=True, context={'version': request.version, 'request': request})
            return self.get_paginated_response(serializer.data)

        serializer = serializer_class(queryset, many=True, context={'version': request.version, 'request': request})
        return OCPIResponse(serializer.data)

# def group_by_value(pairs):
#     """
#     Group adjacent elements together if they share a key
#     This would be used for grouping ChargingPeriods according to Tariffs, but it is not needed currently
#
#     >>> group_by_value([(1, 2), (4, 2), (7, 2), (10, 3), (13, 3), (18, 3), (19, 2)])
#     [(2, [1, 4, 7]), (3, [10, 13, 18]), (2, [19])]
#     """
#     from itertools import groupby
#
#     result = []
#
#     for key, group in groupby(pairs, lambda x: x[1]):
#         result.append((key, [i[0] for i in group]))
#
#     return result


class CiStringField(serializers.CharField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        return data.upper()


class CiStringChoiceField(serializers.ChoiceField):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def to_internal_value(self, data):
        return super().to_internal_value(data.upper())


class MultipleChoiceFieldList(serializers.MultipleChoiceField):
    def to_representation(self, value):
        # The output needs to be JSON serializable, type "set" is not
        return list(super().to_representation(value))


class CountryCodeField(CiStringChoiceField):
    def __init__(self, *args, **kwargs):
        super().__init__(choices=choices.COUNTRY_CHOICES, required=True, *args, **kwargs)


class PartyIdField(CiStringField):
    def __init__(self, *args, **kwargs):
        super().__init__(required=True, max_length=3, *args, **kwargs)


def fetch_object(uid: str, party: Party = None, credentials=None, ocpi_module: OcpiModuleEnum = None) -> bool:
    """
    Find and fetch an object over the OCPI network. Used primarily when somebody PUTs an object which refers to
    a missing Tariff or Location.

    @param uid: The UID or ID of the wanted object
    @param party: The party to fetch the object from (optional to credentials)
    @param credentials: The credentials to use for the fetch (optional to party)
    @param ocpi_module: The OCPI module, e.g. Location, Tariff, etc.
    @return: The fetched object
    """

    route = find_route(party or credentials, ocpi_module, role=EndpointRoleEnum.SENDER)
    if not route:
        from ocpi22 import logging
        logging.error(f'No route found to fetch {ocpi_module.value} with id: "{id}"')
        return False
    role = ocpi_module.get_owner()
    party = party or credentials.get_party_for_role(role)
    url = f'{route.url}/{party.country_code}/{party.party_id}/{uid}'
    our_party = get_our_party(OcpiRolesEnum.EMSP)  # eMSP is receiving Locations, which may have broken references

    # print(f'Fetching missing {ocpi_module.value} from {party} at {url}')
    response = send_ocpi_request(data=dict(), url=url, token_base64=credentials.theirs_base64(),  method='GET',
                                 to_country_code=party.country_code, to_party_id=party.party_id,
                                 from_country_code=our_party.country_code, from_party_id=our_party.party_id,
                                 title='tariff')
    # ic(url, response)
    data = response.get('json')
    data = data.get('data', data)  # Do we have the actual data one level deeper?
    version = route.version
    from ocpi22 import logging
    if data:
        viewset = import_string(ocpi_module.get_viewset())
        response = viewset().put(request=None, data=data, version=version)
        if response.status_code in {200, 201}:
            logging.info(f'Fetched missing {ocpi_module.value} with id: "{uid}"')
            return True
    logging.warning(f'Unable to fetch {ocpi_module.value} with id: "{uid}"')
    return False
