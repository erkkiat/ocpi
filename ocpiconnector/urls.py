from django.conf.urls import include
from django.contrib import admin
from django.urls import path

from rest_framework import routers, serializers, viewsets, mixins
from rest_framework.viewsets import GenericViewSet

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

    class Meta:
        model = Connector
        fields = ['uid', 'standard', 'format',
                  'power_type', 'max_voltage', 'max_amperage', 'max_electric_power',
                  'terms_and_conditions', 'last_updated']


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
    evses = EvseSerializer(many=True, read_only=True)
    operator = BusinessDetailsSerializer(read_only=True, many=True)
    suboperator = BusinessDetailsSerializer(read_only=True, many=True)
    owner = BusinessDetailsSerializer(read_only=True, many=True)

    class Meta:
        model = Location
        exclude = ['lat_partition', 'long_partition', 'facilities', 'url']


class LocationViewSet(mixins.RetrieveModelMixin,
                   mixins.ListModelMixin,
                   GenericViewSet):
    # noinspection PyUnresolvedReferences
    queryset = Location.objects.all().order_by('id')
    serializer_class = LocationSerializer


# class EvseViewSet(mixins.RetrieveModelMixin,
#                    mixins.ListModelMixin,
#                    GenericViewSet):
#     # noinspection PyUnresolvedReferences
#     queryset = Evse.objects.all().order_by('id')
#     serializer_class = EvseSerializer


# class BusinessDetailsViewSet(mixins.RetrieveModelMixin,
#                    mixins.ListModelMixin,
#                    GenericViewSet):
#     # noinspection PyUnresolvedReferences
#     queryset = BusinessDetails.objects.all().order_by('id')
#     serializer_class = BusinessDetailsSerializer


class DocumentedRouter(routers.DefaultRouter):
    APIRootView = TokenAPIView


# Routers provide an easy way of automatically determining the URL conf.
router = DocumentedRouter()
router.register(r'tokens', TokenViewSet)
router.register(r'locations', LocationViewSet)
# router.register(r'evses', EvseViewSet)
# router.register(r'businessdetails', BusinessDetailsViewSet)
# router.register(r'connectors', ConnectorViewSet)

urlpatterns = [
    path('ocpi/2.2/', include(router.urls)),
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    path('admin/', admin.site.urls),
    # path('admin/doc/', include('django.contrib.admindocs.urls')),
]
