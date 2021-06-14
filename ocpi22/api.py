from django.db.models import QuerySet
from collections import OrderedDict
from datetime import datetime

from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import routers, serializers, status, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from ocpi22.models import Token, Tariff, Session, Cdr, Credentials
from ocpi22.versions import get_endpoints_dict


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


class TokenSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Token
        fields = ['detail_url', 'country_code', 'party_id', 'uid', 'type',
                  'contract_id', 'visual_number', 'issuer', 'group_id',
                  'valid', 'whitelist', 'language', 'default_profile_type', 'last_updated']


class CdrTokenSerializer(HyperlinkedModelSerializerCleanedUp):
    """
    Used for showing limited Token information when serializing a CDR
    """

    class Meta:
        model = Token
        fields = ['uid', 'type', 'contract_id']


class TokenViewSet(mixins.UpdateModelMixin,
                   mixins.RetrieveModelMixin,
                   mixins.ListModelMixin,
                   GenericViewSet):
    # noinspection PyUnresolvedReferences
    queryset = Token.objects.all().order_by('created')
    serializer_class = TokenSerializer
    pagination_class = OCPIPaginationAndHeaders

    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['country_code', 'party_id', 'type']

    # Todo: Create a completely new object using PUT
    # noinspection PyUnresolvedReferences
    @action(methods=['GET', 'PUT', 'PATCH'], detail=False,
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def by_id(self, request, country_code, party_id, uid) -> Response:
        token = get_object_or_404(Token, country_code=country_code, party_id=party_id, uid=uid)
        method_is_patch = True if request.method == 'PATCH' else False

        if request.method == 'GET':
            serializer = TokenSerializer(token, many=False, context={'request': request})
            return OCPIResponse(serializer.data)

        elif request.method in ('PUT', 'PATCH'):
            serializer = TokenSerializer(token,
                                         data=request.data,
                                         partial=method_is_patch,
                                         context={'request': request})
            if serializer.is_valid():
                serializer.save()
                return OCPIResponse(serializer.data)
            else:
                return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST)

        return OCPIResponse(http_status=status.HTTP_400_BAD_REQUEST)


class CdrSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Cdr
        fields = ['detail_url', 'country_code', 'party_id', 'uid', 'start_date_time', 'end_date_time',
                  'session_id', 'cdr_token', 'auth_method', 'authorization_reference',
                  'cdr_location', 'tariffs', 'total_cost', 'total_energy',
                  'total_time', 'credit', 'credit_reference_id', 'last_updated']

    cdr_token = CdrTokenSerializer(read_only=True)
    total_cost = serializers.SerializerMethodField()
    tariffs = serializers.SerializerMethodField()

    @staticmethod
    def get_total_cost(obj):
        return get_total_cost(obj)

    @staticmethod
    def get_tariffs(cdr):
        return [t.uid for t in cdr.tariffs.all()]


class CdrViewSet(mixins.RetrieveModelMixin,
                 mixins.ListModelMixin,
                 GenericViewSet):
    """
    These are the Charge Detail Records. Once a CDR is created, it must not be modified or removed.
    A CDR can be credited to the customer by creating a credit CDR in the admin user interface.
    """
    # noinspection PyUnresolvedReferences
    queryset = Cdr.objects.all().order_by('created')
    serializer_class = CdrSerializer
    pagination_class = OCPIPaginationAndHeaders

    @action(methods=['GET'], detail=False, url_name='cdr-by-id',
            url_path='(?P<uid>[^/.]+)')
    def cdr_by_id(self, request, uid) -> Response:
        cdr = get_object_or_404(Cdr, uid=uid)
        serializer = CdrSerializer(cdr, many=False, context={'request': request})
        return OCPIResponse(serializer.data)


class CredentialsViewSet(mixins.CreateModelMixin,
                         viewsets.ViewSet):
    """
    Credential tokens exchange.
    """
    # noinspection PyUnresolvedReferences
    queryset = Credentials.objects.none()
    # serializer_class = CdrSerializer
    # pagination_class = OCPIPaginationAndHeaders

    @action(methods=['POST'], detail=False, url_name='',
            url_path='')
    def credentials(self, request) -> Response:
        return OCPIResponse(dict(posted=0))

    def get(self, request):
        return OCPIResponse(status_code=Ocpi.ClientError.GENERIC_CLIENT_ERROR,
                            status_message='Credentials can only be posted')


def clear_empty(dict_with_possibly_empty_values):
    return OrderedDict((k, v) for k, v in dict_with_possibly_empty_values.items()
                       if v not in [None, [], '', {}])


def get_total_cost(obj):
    return clear_empty(dict(
        excl_vat=obj.total_cost_excl_vat,
        incl_vat=obj.total_cost_incl_vat
    ))


class SessionSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Session
        fields = ['detail_url', 'country_code', 'party_id', 'uid',
                  'start_date_time', 'end_date_time', 'kwh',
                  'cdr_token', 'auth_method', 'authorization_reference',
                  'location_id', 'evse_uid', 'connector_id', 'meter_id', 'currency', 'total_cost',
                  'status', 'last_updated']

    uid = serializers.CharField(read_only=True)
    cdr_token = serializers.SerializerMethodField()
    location_id = serializers.SerializerMethodField()
    evse_uid = serializers.SerializerMethodField()
    connector_id = serializers.SerializerMethodField()
    total_cost = serializers.SerializerMethodField()

    @staticmethod
    def get_cdr_token(session):
        token = session.cdr_token
        return clear_empty(dict(
            uid=token.uid,
            type=token.type,
            contract_id=token.contract_id
        ))

    @staticmethod
    def get_location_id(session):
        return session.location.uid

    @staticmethod
    def get_evse_uid(session):
        return session.evse.uid

    @staticmethod
    def get_connector_id(session):
        return session.connector.uid

    @staticmethod
    def get_total_cost(obj):
        return get_total_cost(obj)


class TariffSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Tariff
        fields = ('detail_url', 'readable', 'country_code', 'party_id', 'id', 'type',
                  'tariff_alt_url', 'elements', 'last_updated')

    id = serializers.CharField(source='uid', read_only=True)
    elements = serializers.SerializerMethodField()
    readable = serializers.SerializerMethodField()

    @staticmethod
    def get_elements(tariff: Tariff) -> dict:
        # noinspection PyUnresolvedReferences
        price_components = [
            dict(
                type=pc.type,
                price=pc.price,
                vat=pc.vat,
                step_size=pc.step_size
            )
            for pc in tariff.price_components.all()
        ]
        for pc in price_components:
            if not pc.get('vat'):
                pc.pop('vat')
        return dict(price_components=price_components)

    @staticmethod
    def get_readable(tariff: Tariff) -> str:
        return str(tariff)


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


class TariffViewSet(mixins.RetrieveModelMixin,
                    mixins.ListModelMixin,
                    GenericViewSet):
    # noinspection PyUnresolvedReferences
    queryset = Tariff.objects.all().order_by('created')
    serializer_class = TariffSerializer
    pagination_class = OCPIPaginationAndHeaders

    # Todo: Create a completely new object using PUT

    @action(methods=['GET'], detail=False, description='Get a single Tariff by country, party and uid',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def by_id(self, request, country_code, party_id, uid) -> Response:
        tariff = get_object_or_404(Tariff, country_code=country_code, party_id=party_id, uid=uid)
        serializer = TariffSerializer(tariff, many=False, context={'request': request})
        return OCPIResponse(serializer.data)


class SessionViewSet(mixins.ListModelMixin,
                     mixins.RetrieveModelMixin,
                     GenericViewSet):
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['country_code', 'party_id', 'status', 'meter_id', 'cdr_token', 'authorization_reference']
    pagination_class = OCPIPaginationAndHeaders

    @action(methods=['GET'], detail=False, url_name='by-id',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def session_by_id(self, request, country_code, party_id, uid) -> Response:
        # noinspection PyUnresolvedReferences
        session = get_object_or_404(Session, country_code=country_code, party_id=party_id, uid=uid)

        if request.method == 'GET':
            serializer = SessionSerializer(session, context={'request': request})
            return OCPIResponse(serializer.data)

        # elif request.method == 'PATCH':
        #     serializer = SessionSerializer(session, data=request.data, partial=True, context={'request': request})
        #     if serializer.is_valid():
        #         serializer.save()
        #         return OCPIResponse(serializer.data)
        #     else:
        #         return OCPIResponse(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return OCPIResponse(http_status=status.HTTP_400_BAD_REQUEST)

    # noinspection PyUnresolvedReferences
    queryset = Session.objects.all().order_by('created')
    serializer_class = SessionSerializer


class OCPIResponse(Response):
    def __init__(self, data='', status_code=1000, status_message='', http_status=status.HTTP_200_OK, errors=None):
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
        super().__init__(result, status=http_status)


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


class OcpiApi22View(routers.APIRootView):
    """
    This portal provides ways to view the information in the database, read the API documentation and
    try out sending information to the API.

    The streamlined interfaces for the CPO are available at [/api/cpo/v1/](/api/cpo/v1/).
    You can contact [support@chargerhub.eu](support@chargerhub.eu) for more information.
    """
    def get(self, request, **kwargs):
        return Response(get_endpoints_dict(request))

    def get_view_name(self):
        return 'OCPI 2.2'


class OCPIRouter(routers.DefaultRouter):
    APIRootView = OcpiApi22View
    root_view_name = 'ocpi-22'
