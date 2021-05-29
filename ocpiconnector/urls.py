from collections import OrderedDict
from datetime import datetime

from django.conf.urls import include
from django.contrib import admin
from django.db.models import QuerySet
from django.urls import path

from rest_framework import routers, serializers, viewsets, mixins
from rest_framework.decorators import action
from rest_framework.viewsets import GenericViewSet
from rest_framework.response import Response

from ocpi22.models import Token, Location, Connector, Evse, BusinessDetails, Tariff


class HyperlinkedModelSerializerCleanedUp(serializers.HyperlinkedModelSerializer):
    def to_representation(self, value):
        # Remove empty values
        repr_dict = super().to_representation(value)
        return OrderedDict((k, v) for k, v in repr_dict.items()
                           if v not in [None, [], '', {}])


class TokenSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Token
        exclude = ['url']


class TokenViewSet(viewsets.ModelViewSet):
    # noinspection PyUnresolvedReferences
    queryset = Token.objects.all().order_by('created')
    serializer_class = TokenSerializer


class TokenAPIView(routers.APIRootView):
    """
    OCPI version 2.2
    ---------------

    The Charger API provides ways to access the charge point database.

    * The paged endpoint below lists all European chargers for creating a daily or weekly mirror of the database.
    * See below link for further search endpoints.
    * The list of codes used here are available at [/api/v1/common/codes/](/api/v1/common/codes/)
    """
    pass


class ConnectorSerializer(HyperlinkedModelSerializerCleanedUp):
    uid = serializers.CharField()
    max_electric_power = serializers.SerializerMethodField()

    class Meta:
        model = Connector
        fields = ['uid', 'standard', 'format',
                  'power_type', 'max_voltage', 'max_amperage', 'max_electric_power',
                  'terms_and_conditions', 'last_updated']

    def get_max_electric_power(self, connector: Connector) -> str:
        # Todo: what about 1-phase and 2-phase AC?
        return connector.max_electric_power or connector.max_voltage * connector.max_amperage


class BusinessDetailsSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = BusinessDetails
        exclude = ['url']


class EvseSerializer(HyperlinkedModelSerializerCleanedUp):
    connectors = ConnectorSerializer(many=True, read_only=True)

    class Meta:
        model = Evse
        exclude = ['capabilities', 'url', 'location']


class TariffSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Tariff
        fields = ('country_code', 'party_id', 'id', 'type', 'tariff_alt_url', 'elements', 'last_updated')

    id = serializers.CharField(source='uid')
    elements = serializers.SerializerMethodField()

    @staticmethod
    def get_elements(tariff: Tariff) -> dict:
        # noinspection PyUnresolvedReferences
        result = price_components=[
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
        return dict(price_components=result)


class LocationSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Location
        exclude = ['lat_partition', 'long_partition', 'facilities', 'url', 'uid', 'latitude', 'longitude']

    id = serializers.CharField(source='uid')
    coordinates = serializers.SerializerMethodField()
    evses = EvseSerializer(many=True, read_only=True)
    operator = BusinessDetailsSerializer(read_only=True, many=False)
    suboperator = BusinessDetailsSerializer(read_only=True, many=False)
    owner = BusinessDetailsSerializer(read_only=True, many=False)
    publish_allowed_to = serializers.SerializerMethodField()

    def get_coordinates(self, location: Location) -> dict:
        return dict(latitude=location.latitude, longitude=location.longitude)

    def get_publish_allowed_to(self, location: Location) -> list:
        """
        List the token IDs of the drivers who are allowed to see this Location
        """
        return [token.uid for token in location.publish_allowed_to.all()]


def apply_ocpi22_query_parameters(request, queryset) -> QuerySet:
    date_from: str = request.GET.get('date_from')
    if date_from:
        import dateutil.parser
        date_from: datetime = dateutil.parser.isoparse(date_from)
        queryset = queryset.filter(last_updated__gte=date_from)
    date_to: str = request.GET.get('date_to')
    if date_to:
        import dateutil.parser
        date_to: datetime = dateutil.parser.isoparse(date_to)
        queryset = queryset.filter(last_updated__lt=date_to)
    limit: int = int(request.GET.get('limit', '0'))
    offset: int = int(request.GET.get('offset', '0'))

    queryset = queryset.order_by('id')
    if limit:
        queryset = queryset[offset:offset + limit]
    return queryset


class TariffViewSet(ViewSet):
    # noinspection PyUnresolvedReferences
    queryset = Tariff.objects.all().order_by('created')

    @action(methods=['GET'], detail=False)
    def tariffs(self, request) -> Response:
        # noinspection PyUnresolvedReferences
        queryset = apply_ocpi22_query_parameters(request, Tariff.objects.all().order_by('created'))
        serializer = TariffSerializer(queryset, many=True)
        return Response(serializer.data)

    # noinspection PyUnresolvedReferences
    @action(methods=['GET'], detail=False, description='Get a single Tariff by country, party and uid',
            url_path='tariffs/(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def by_id(self, _request, country_code, party_id, uid) -> Response:
        try:
            tariff = Tariff.objects.get(country_code=country_code, party_id=party_id, uid=uid)
            serializer = TariffSerializer(tariff, many=False)
            return Response(serializer.data)
        except Tariff.DoesNotExist:
            return Response(status=404)


class LocationViewSet(GenericViewSet):

    @action(methods=['GET'], detail=False)
    def locations(self, request) -> Response:
        # noinspection PyUnresolvedReferences
        queryset = apply_ocpi22_query_parameters(request, Location.objects.all())
        serializer = LocationSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(methods=['GET'], detail=False, url_path='locations/(?P<uid>[^/.]+)')
    def location_by_id(self, request, uid) -> Response:
        # noinspection PyUnresolvedReferences
        queryset = Location.objects.filter(uid=uid)
        serializer = LocationSerializer(queryset, many=True)
        return Response(serializer.data)

    # @action(methods=['GET'], detail=False, url_path='locations/(?P<uid>[^/.]+)/(?P<evse_id>[^/.]+)')
    # def location_by_uid(self, request, uid, evse_id):
    #     # noinspection PyUnresolvedReferences
    #     queryset = Location.objects.filter(uid=uid)
    #     serializer = LocationSerializer(queryset, many=True)
    #     return Response(serializer.data)

    # noinspection PyUnresolvedReferences
    queryset = Location.objects.all().order_by('id')


class DocumentedRouter(routers.DefaultRouter):
    APIRootView = TokenAPIView


# Routers provide an easy way of automatically determining the URL conf.
router = DocumentedRouter()
router.register(r'tokens', TokenViewSet)
router.register(r'', LocationViewSet)
router.register(r'', TariffViewSet)

urlpatterns = [
    path('ocpi/2.2/', include(router.urls)),
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    path('admin/', admin.site.urls),
    # path('admin/doc/', include('django.contrib.admindocs.urls')),
]
