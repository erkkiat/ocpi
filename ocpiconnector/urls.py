from datetime import datetime

from django.conf.urls import include
from django.contrib import admin
from django.db.models import QuerySet
from django.urls import path

from rest_framework import routers, serializers, viewsets, mixins
from rest_framework.decorators import action
from rest_framework.viewsets import GenericViewSet
from rest_framework.response import Response

from ocpi22.models import Token, Location, Connector, Evse, BusinessDetails


class TokenSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Token
        exclude = []


class TokenViewSet(viewsets.ModelViewSet):
    # noinspection PyUnresolvedReferences
    queryset = Token.objects.all()
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



class ConnectorSerializer(serializers.HyperlinkedModelSerializer):
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


class BusinessDetailsSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = BusinessDetails
        exclude = ['url']


class EvseSerializer(serializers.HyperlinkedModelSerializer):
    connectors = ConnectorSerializer(many=True, read_only=True)

    class Meta:
        model = Evse
        exclude = ['capabilities', 'url', 'location']


class LocationSerializer(serializers.HyperlinkedModelSerializer):
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

    def get_coordinates(self, location: Location):
        return dict(latitude=location.latitude, longitude=location.longitude)

    def get_publish_allowed_to(self, location: Location) -> list:
        """
        List the token IDs of the drivers who are allowed to see this Location
        """
        return [token.uid for token in location.publish_allowed_to.all()]


def apply_query_date_range(request, queryset) -> QuerySet:
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


class LocationViewSet(GenericViewSet):
    @action(methods=['GET'], detail=False)
    def locations(self, request):
        # noinspection PyUnresolvedReferences
        queryset = apply_query_date_range(request, Location.objects.all())
        serializer = LocationSerializer(queryset, many=True)
        return Response(serializer.data)

    # noinspection PyUnresolvedReferences
    queryset = Location.objects.all().order_by('id')


class DocumentedRouter(routers.DefaultRouter):
    APIRootView = TokenAPIView


# Routers provide an easy way of automatically determining the URL conf.
router = DocumentedRouter()
router.register(r'tokens', TokenViewSet)
router.register(r'', LocationViewSet)
# router.register(r'evses', EvseViewSet)
# router.register(r'businessdetails', BusinessDetailsViewSet)
# router.register(r'connectors', ConnectorViewSet)

urlpatterns = [
    path('ocpi/2.2/', include(router.urls)),
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    path('admin/', admin.site.urls),
    # path('admin/doc/', include('django.contrib.admindocs.urls')),
]
