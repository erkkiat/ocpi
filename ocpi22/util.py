import json
import logging
import secrets
from collections import OrderedDict
from datetime import datetime

import requests
from django.conf import settings
from django.core.validators import RegexValidator
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.module_loading import import_string
from icecream import ic
from requests import Response
from rest_framework import serializers, status, exceptions
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response


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
    '1 h 30 min'
    >>> hours_minutes(.5)
    '30 min'
    >>> hours_minutes(2/3600)
    '2 seconds'
    """

    hours = int(hours_float)
    minutes = int((hours_float-hours)*60)
    if hours:
        return f'{hours} h {minutes} min'
    elif not hours and not minutes:
        seconds = int(hours_float*3600)
        return f'{seconds} seconds'
    else:
        return f'{minutes} min'


def generate_random_token() -> str:
    """
    >>> len(generate_random_token())
    64
    >>> generate_random_token() != generate_random_token()
    True
    """
    return secrets.token_hex(32)


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

    detail_url = serializers.SerializerMethodField(read_only=True)
    url = serializers.SerializerMethodField(read_only=True)
    quick_url = serializers.SerializerMethodField(read_only=True)
    status_url = serializers.SerializerMethodField(read_only=True)


def apply_ocpi22_filters(request, queryset) -> QuerySet:
    """
    Apply the OCPI 2.2 filters to a queryset (date range, limit, offset)
    :param request:
    :param queryset:
    :return:
    """
    date_from: str = request.GET.get('date_from')
    if date_from:
        import dateutil.parser
        date_from: datetime = dateutil.parser.parse(date_from, ignoretz=True)
        queryset = queryset.filter(last_updated__gte=date_from)
    date_to: str = request.GET.get('date_to')
    if date_to:
        import dateutil.parser
        date_to: datetime = dateutil.parser.parse(date_to, ignoretz=True)
        queryset = queryset.filter(last_updated__lt=date_to)
    # limit: int = int(request.GET.get('limit', '0'))
    # offset: int = int(request.GET.get('offset', '0'))
    #
    # queryset = queryset.order_by('created')
    # if limit:
    #     queryset = queryset[offset:offset + limit]
    return queryset


class OCPIPaginationAndHeaders(LimitOffsetPagination):
    default_limit = 100

    def get_paginated_response(self, data):
        headers = {
            'X-Total-Count': self.count,
            'X-Limit': self.default_limit,
        }

        next_url = self.get_next_link()
        if next_url:
            headers['Link'] = '<{next_url}; rel="next">'.format(next_url=self.get_next_link())

        return Response(OrderedDict([
            ('status_code', 1000),
            ('timestamp', timezone.now()),
            ('data', data),
        ]), headers=headers)

    def paginate_queryset(self, queryset, request, view=None):
        queryset = apply_ocpi22_filters(request, queryset)
        return super().paginate_queryset(queryset, request, view)


class Ocpi:
    class ClientError:
        # Todo: Check that these are used
        GENERIC_CLIENT_ERROR = 2000
        INVALID_OR_MISSING_PARAMETERS = 2001
        NOT_ENOUGH_INFORMATION = 2002
        UNKNOWN_LOCATION = 2003
        UNKNOWN_TOKEN = 2004

    class ServerError:
        GENERIC_SERVER_ERROR = 3000
        UNABLE_TO_USE_CLIENTS_API = 3001
        UNSUPPORTED_VERSION = 3002
        NO_MATCHING_ENDPOINTS = 3003

    class HubError:
        UNKNOWN_RECEIVER = 4001
        TIMEOUT_ON_FORWARDED_REQUEST = 4002
        CONNECTION_PROBLEM = 4003

    class Modules:
        LOCATIONS = 'locations'
        TARIFFS = 'tariffs'
        TOKENS = 'tokens'
        CREDENTIALS = 'credentials'
        SESSIONS = 'sessions'
        CDRS = 'cdrs'
        COMMANDS = 'commands'


class OCPIResponse(Response):
    def __init__(self, data='', status_code=1000, status_message='', http_status=status.HTTP_200_OK, errors=None,
                 *args, **kwargs):
        if isinstance(status_message, list):
            status_message = ', '.join([s for s in status_message])
        if isinstance(errors, dict):
            status_message = ', '.join([f"{field}: {error}" for field, error in errors.items()])
            data = errors  # This is a courtacy, it's not OCPI compliant
            status_code = Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS
            http_status = status.HTTP_400_BAD_REQUEST
            logging.error(status_message)
        result = dict(
            status_code=status_code,
            status_message=status_message,
            timestamp=timezone.now(),
            data=data
        )
        super().__init__(result, status=http_status, *args, **kwargs)


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
    if check_operator_id_from_request_data and hasattr(request, 'data'):
        cc = request.data.get('country_code')
        pi = request.data.get('party_id')
        if (cc and cc != country_code) or (pi and pi != party_id):
            return False
    for role in request.credentials.roles.all():
        if role.country_code == country_code and role.party_id == party_id:
            return True
    return False


class NotOwner(OCPIResponse):
    def __init__(self):
        super().__init__(
            status_message="Country ID and Party ID need to match your credentials.",
            status_code=2002,
            http_status=status.HTTP_403_FORBIDDEN)


class OCPIBadRequestResponse(OCPIResponse):
    def __init__(self):
        super().__init__(
            status_code=2001,
            http_status=status.HTTP_400_BAD_REQUEST)


def matching_operator(request, country_code, party_id) -> bool:
    if request.user.is_staff:
        return True
    if not hasattr(request, 'credentials'):
        return False
    for r in request.credentials.roles.all():
        if r.country_code == country_code and r.party_id == party_id:
            return True
    return False


class OcpiModule:
    ocpi_serializer_class = None
    ocpi_module_name = None

    def atomic_post_save(self, *args, **kwargs) -> None:
        ic("Generic atomic_post_save")
        ic(args, kwargs)

        assert self.ocpi_serializer_class, \
            f'OCPI object class {type(self)} must have an ocpi_serializer_class specified.'
        assert self.ocpi_module_name, \
            f'OCPI object class {type(self)} must have an ocpi_module_name specified.'

        if not hasattr(self, 'update_sent') and self.is_ours():
            if not hasattr(self, 'archived') or self.archived == False:
                print('*** This is our object, sending updates to all known parties')
                self.send_updates()
                # Send update only once
                setattr(self, 'update_sent', True)

    def send_updates(self) -> None:
        """
        Find all endpoints interested in Tariff updates and send update in a background task.
        To disable updates, set env SEND_UPDATES to false
        """

        ocpi_module = self.ocpi_module_name
        serializer_class = self.ocpi_serializer_class

        if isinstance(serializer_class, str):
            serializer_class = import_string(serializer_class)

        if settings.SEND_UPDATES > 0:
            from ocpi22.models.credentials import Endpoint
            # noinspection PyUnresolvedReferences
            endpoints = Endpoint.objects.filter(identifier=ocpi_module, role='RECEIVER')
            serializer = serializer_class(self)
            e: Endpoint
            for e in endpoints:
                print(f'Send update to {ocpi_module} module at {e.url}')
                from ocpi22.tasks import send_update
                if settings.BACKGROUND_SEND:
                    send_update.delay(serializer.data, e.url, e.get_token_base64())
                else:
                    send_update(serializer.data, e.url, e.get_token_base64())
        else:
            logging.warning(settings.UPDATES_DISABLED)


def ocpi_post(url, token_base64, *args, **kwargs) -> Response:
    print(f'Posting to {url}')
    data = ''
    if 'data' in kwargs:
        data = json.dumps(kwargs.pop('data'))
        # ic(data)
    response = requests.post(url, *args, **kwargs, data=data,
                             headers={
                                 "Authorization": f'Token {token_base64}',
                                 'content-type': 'application/json',
                             })
    if response.status_code not in (200, 403, 404):
        print(f'*** Got response: {response.status_code} - {response.reason}')
        logging.error(response.text)
        raise exceptions.APIException(f'Got response for {url}: {response.status_code} - {response.reason} ')
    return response


def pretty_currency(c):
    """
    Apply a currency symbol if such is known
    >>> pretty_currency('EUR')
    '€'
    """
    return dict(EUR='€', GBP='£', USD='$').get(c, c)


def format_currency(number: float, currency: str) -> str:
    """
    >>> format_currency(1.1, 'EUR')
    '1,10€'
    >>> format_currency(1.12, 'EUR')
    '1,12€'
    >>> format_currency(1.123, 'EUR')
    '1,12€'
    >>> format_currency(1.0, 'EUR')
    '1€'
    """
    currency = pretty_currency(currency)
    if float(int(number)) == number:
        result = f"{number:.0f}{currency}"
    else:
        result = f"{number:.2f}{currency}"
    return result.replace(".", settings.DECIMAL_SEPARATOR)


def format_cost(incl_vat: float, excl_vat: float, currency: str) -> str:
    """
    Format a string which hides zero values and shows the price with and without tax, if available
    >>> format_cost(1.2, 1.0, "EUR")
    '1,20€'
    >>> format_cost(1.2, 0.0, "EUR")
    '1,20€'
    >>> format_cost(0.0, 1.0, "EUR")
    '1€ (VAT 0%)'
    >>> format_cost(0.0, 0.0, "EUR")
    '-'
    """

    cost_format = "{excl_vat} (VAT 0%)"
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


class ModelUtilMixin:
    @classmethod
    def get_if_exists(cls, *args: list, **kwargs: dict):
        # noinspection PyUnresolvedReferences
        objects = cls.objects.filter(*args, **kwargs)
        if objects.count():
            return objects[0]
        return None

    def party(self) -> str:
        if hasattr(self, 'location'):
            return f'{self.location.country_code}*{self.location.party_id}'
        if hasattr(self, 'country_code') and hasattr(self, 'party_id'):
            return f'{self.country_code}*{self.party_id}'
        return ''

    # noinspection PyUnresolvedReferences
    def is_ours(self) -> bool:
        # Returns true if we hold the master data for this object
        if hasattr(self, 'country_code') and self.country_code != settings.COUNTRY_CODE:
            return False
        if hasattr(self, 'party_id') and self.party_id != settings.PARTY_ID:
            return False
        return True

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


uid_validator = RegexValidator(r'^[0-9a-zA-Z\*\-]+$', message='Numbers and letters only')