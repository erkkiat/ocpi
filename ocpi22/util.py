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


class OCPIResponse(Response):
    def __init__(self, data='', status_code=1000, status_message='', http_status=status.HTTP_200_OK, errors=None,
                 *args, **kwargs):
        if isinstance(status_message, list):
            status_message = ', '.join([s for s in status_message])
        if isinstance(errors, dict):
            status_message = ', '.join([f"{field}: {error}" for field, error in errors.items()])
            data = errors  # This is a courtacy, it's not OCPI compliant
            status_code = Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS
        result = dict(
            status_code=status_code,
            status_message=status_message,
            timestamp=timezone.now(),
            data=data
        )
        super().__init__(result, status=http_status, *args, **kwargs)
