from django.db.models import QuerySet
from collections import OrderedDict
from datetime import datetime

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import routers, serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from ocpi22.models import Token, Location, Connector, Evse, BusinessDetails, Tariff, Session


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

    detail_url = serializers.SerializerMethodField(read_only=True)
    url = serializers.SerializerMethodField(read_only=True)


class OCPIViewSetMixin:
    """
    Apply the OCPI filters to the queryset
    """

    # noinspection PyUnresolvedReferences
    def get_queryset(self):
        return apply_ocpi22_filters(self.request, self.queryset)


class TokenSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Token
        fields = ['detail_url', 'country_code', 'party_id', 'uid', 'type',
                  'contract_id', 'visual_number', 'issuer', 'group_id',
                  'valid', 'whitelist', 'language', 'default_profile_type', 'last_updated']


class TokenViewSet(viewsets.ModelViewSet, OCPIViewSetMixin):
    # noinspection PyUnresolvedReferences
    queryset = Token.objects.all().order_by('created')
    serializer_class = TokenSerializer

    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['country_code', 'party_id', 'type']

    # noinspection PyUnresolvedReferences
    @action(methods=['GET', 'PUT', 'PATCH'], detail=False,
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def by_id(self, request, country_code, party_id, uid) -> Response:
        token = get_object_or_404(Token, country_code=country_code, party_id=party_id, uid=uid)
        method_is_patch = True if request.method == 'PATCH' else False

        if request.method == 'GET':
            serializer = TokenSerializer(token, many=False, context={'request': request})
            return Response(serializer.data)

        elif request.method in ('PUT', 'POST', 'PATCH'):
            serializer = TokenSerializer(token,
                                         data=request.data,
                                         partial=method_is_patch,
                                         context={'request': request})
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_400_BAD_REQUEST)


class ConnectorSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Connector
        fields = ['uid', 'standard', 'format',
                  'power_type', 'max_voltage', 'max_amperage', 'max_electric_power',
                  'tariff_ids', 'terms_and_conditions', 'last_updated']

    uid = serializers.CharField()
    max_electric_power = serializers.SerializerMethodField()
    tariff_ids = serializers.SerializerMethodField()

    @staticmethod
    def get_tariff_ids(connector: Connector) -> dict:
        return [t.uid for t in connector.tariff_ids.all()]

    @staticmethod
    def get_max_electric_power(connector: Connector) -> str:
        # Todo: what about 1-phase and 2-phase AC?
        return connector.max_electric_power or connector.max_voltage * connector.max_amperage


class BusinessDetailsSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = BusinessDetails
        fields = ['name', 'website', 'logo']


class EvseSerializer(HyperlinkedModelSerializerCleanedUp):
    connectors = ConnectorSerializer(many=True, read_only=True)

    class Meta:
        model = Evse
        fields = ['detail_url', 'uid', 'evse_id', 'status', 'last_updated', 'connectors']


def clear_empty(dict_with_possibly_empty_values):
    return OrderedDict((k, v) for k, v in dict_with_possibly_empty_values.items()
                if v not in [None, [], '', {}])


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
    def get_total_cost(session):
        return clear_empty(dict(
            excl_vat=session.total_cost_excl_vat,
            incl_vat=session.total_cost_incl_vat
        ))


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


class LocationSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Location
        fields = ['detail_url', 'country_code', 'party_id', 'id', 'publish', 'publish_allowed_to',
                  'name', 'address', 'city', 'postal_code', 'state', 'country',
                  'coordinates', 'parking_type', 'evses',
                  'operator', 'suboperator', 'owner',
                  'facilities', 'time_zone', 'last_updated']

    id = serializers.CharField(source='uid')
    coordinates = serializers.SerializerMethodField()
    evses = EvseSerializer(many=True, read_only=True)
    operator = BusinessDetailsSerializer(read_only=True, many=False)
    suboperator = BusinessDetailsSerializer(read_only=True, many=False)
    owner = BusinessDetailsSerializer(read_only=True, many=False)
    publish_allowed_to = serializers.SerializerMethodField()
    facilities = serializers.SerializerMethodField()

    @staticmethod
    def get_coordinates(location: Location) -> dict:
        # Create a dict to be placed one step lower in the json
        return dict(latitude=location.latitude, longitude=location.longitude)

    @staticmethod
    def get_publish_allowed_to(location: Location) -> list:
        """
        List the token IDs of the drivers who are allowed to see this Location
        """
        if location.publish:
            # Location is public to everyone, no need to specify exceptions
            return []
        return [token.uid for token in location.publish_allowed_to.all()]

    @staticmethod
    def get_facilities(location: Location):
        # Create a list of facility names
        return [facility.name for facility in location.facilities.all()]


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
    limit: int = int(request.GET.get('limit', '0'))
    offset: int = int(request.GET.get('offset', '0'))

    queryset = queryset.order_by('created')
    if limit:
        queryset = queryset[offset:offset + limit]
    return queryset


class TariffViewSet(viewsets.ModelViewSet, OCPIViewSetMixin):
    # noinspection PyUnresolvedReferences
    queryset = Tariff.objects.all().order_by('created')
    serializer_class = TariffSerializer

    @action(methods=['GET'], detail=False, description='Get a single Tariff by country, party and uid',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def by_id(self, request, country_code, party_id, uid) -> Response:
        tariff = get_object_or_404(Tariff, country_code=country_code, party_id=party_id, uid=uid)
        serializer = TariffSerializer(tariff, many=False, context={'request': request})
        return Response(serializer.data)


class LocationViewSet(viewsets.ModelViewSet, OCPIViewSetMixin):

    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['country_code', 'party_id', 'parking_type', 'city', 'publish', 'facilities', 'country']

    # Todo: How to PATCH sub-dicts of Locations
    @action(methods=['GET', 'PATCH'], detail=False,
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def by_id(self, request, country_code, party_id, uid) -> Response:
        # noinspection PyUnresolvedReferences
        location = get_object_or_404(Location, country_code=country_code, party_id=party_id, uid=uid)

        if request.method == 'GET':
            serializer = LocationSerializer(location, context={'request': request})
            return Response(serializer.data)

        elif request.method == 'PATCH':
            serializer = LocationSerializer(location, data=request.data, partial=True, context={'request': request})
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_400_BAD_REQUEST)

    # noinspection PyUnresolvedReferences
    queryset = Location.objects.all().order_by('created')
    serializer_class = LocationSerializer


class SessionViewSet(viewsets.ModelViewSet, OCPIViewSetMixin):

    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['country_code', 'party_id', 'status', 'meter_id', 'cdr_token', 'authorization_reference']

    @action(methods=['GET', 'PATCH'], detail=False, url_name='by-id',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def session_by_id(self, request, country_code, party_id, uid) -> Response:
        # noinspection PyUnresolvedReferences
        session = get_object_or_404(Session, country_code=country_code, party_id=party_id, uid=uid)

        if request.method == 'GET':
            serializer = SessionSerializer(session, context={'request': request})
            return Response(serializer.data)

        elif request.method == 'PATCH':
            serializer = SessionSerializer(session, data=request.data, partial=True, context={'request': request})
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_400_BAD_REQUEST)

    # noinspection PyUnresolvedReferences
    queryset = Session.objects.all().order_by('created')
    serializer_class = SessionSerializer


class EvseViewSet(viewsets.ModelViewSet, OCPIViewSetMixin):

    @action(methods=['GET', 'PATCH'], detail=False,
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)/(?P<evse_id>[^/.]+)')
    def by_id(self, request, country_code, party_id, uid, evse_id) -> Response:
        # noinspection PyUnresolvedReferences
        evse = get_object_or_404(Evse, uid=evse_id)
        location = evse.location
        if location.uid != uid or location.party_id != party_id or location.country_code != country_code:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        if request.method == 'GET':
            serializer = EvseSerializer(evse, context={'request': request})
            return Response(serializer.data)

        elif request.method == 'PATCH':
            serializer = EvseSerializer(evse, data=request.data, partial=True, context={'request': request})
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_400_BAD_REQUEST)

    # noinspection PyUnresolvedReferences
    queryset = Evse.objects.all().order_by('created')
    serializer_class = EvseSerializer


class ConnectorAPIView(routers.APIRootView):
    """
    OCPI version 2.2
    ---------------

    This portal provides ways to view the information in the database, read the API documentation and
    try out sending information to the API. The OCPI API serves primarily the eMSP.

    The interfaces for CPO are available at [/api/cpo/v1/](/api/cpo/v1/)
    You can get more information on how to use the information here from [support@chargerhub.eu](support@chargerhub.eu).
    """


class OCPIRouter(routers.DefaultRouter):
    APIRootView = ConnectorAPIView
