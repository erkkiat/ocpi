import logging
import secrets
from collections import OrderedDict
from datetime import datetime

from django.db.models import QuerySet
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response


def clear_empty(dict_with_possibly_empty_values):
    return OrderedDict((k, v) for k, v in dict_with_possibly_empty_values.items()
                       if v not in [None, [], '', {}])


def get_total_cost(obj):
    return clear_empty(dict(
        excl_vat=obj.total_cost_excl_vat,
        incl_vat=obj.total_cost_incl_vat
    ))


def hours_minutes(hours_float):
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
    return secrets.token_hex(32)


class HyperlinkedModelSerializerCleanedUp(serializers.HyperlinkedModelSerializer):
    def to_representation(self, value):
        # Remove empty values
        repr_dict = super().to_representation(value)
        return clear_empty(repr_dict)

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


def matching_operator(request, country_code, party_id) -> bool:
    if request.user.is_staff:
        return True
    if not hasattr(request, 'credentials'):
        return False
    for r in request.credentials.roles.all():
        if r.country_code == country_code and r.party_id == party_id:
            return True
    return False
