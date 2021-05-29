from django.db.models import QuerySet
from collections import OrderedDict
from datetime import datetime

from pytz import timezone
from rest_framework import routers, serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.viewsets import GenericViewSet, ViewSet
from rest_framework.response import Response

from ocpi22.models import Token, Location, Connector, Evse, BusinessDetails, Tariff


class HyperlinkedModelSerializerCleanedUp(serializers.HyperlinkedModelSerializer):
    def to_representation(self, value):
        # Remove empty values
        repr_dict = super().to_representation(value)
        return OrderedDict((k, v) for k, v in repr_dict.items()
                           if v not in [None, [], '', {}])

    def get_detail_url(self, obj):
        request = self.context["request"]
        if not hasattr(obj, 'get_absolute_url'):
            return ''
        return f'{request.build_absolute_uri(obj.get_absolute_url())}'  # return the absolute url of the object

    detail_url = serializers.SerializerMethodField(read_only=True)  # define a SerializerMethodField


class TokenSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Token
        fields = ['detail_url', 'country_code', 'party_id', 'uid', 'type', 'contract_id', 'visual_number', 'issuer', 'group_id',
                  'valid', 'whitelist', 'language', 'default_profile_type', 'last_updated']

    last_updated = serializers.DateTimeField(default_timezone=timezone('UTC'), read_only=True)


class TokenViewSet(viewsets.ModelViewSet):
    # noinspection PyUnresolvedReferences
    queryset = Token.objects.all().order_by('created')
    serializer_class = TokenSerializer

    @action(methods=['GET'], detail=False)
    def tokens(self, request) -> Response:
        # noinspection PyUnresolvedReferences
        queryset = apply_ocpi22_query_parameters(request, Token.objects.all())
        serializer = TokenSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)

    # noinspection PyUnresolvedReferences
    @action(methods=['GET', 'PUT', 'PATCH', 'POST', 'DELETE'], detail=False,
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def by_id(self, request, country_code, party_id, uid) -> Response:
        token = get_object_or_404(Token, country_code=country_code, party_id=party_id, uid=uid)

        if request.method == 'GET':
            serializer = TokenSerializer(token, many=False, context={'request': request})
            return Response(serializer.data)

        elif request.method == 'PUT':
            serializer = TokenSerializer(token, data=request.data, context={'request': request})
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        elif request.method == 'PATCH':
            serializer = TokenSerializer(token, data=request.data, partial=True, context={'request': request})
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        elif request.method == 'POST':
            serializer = TokenSerializer(token, data=request.data, context={'request': request})
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        elif request.method == 'DELETE':
            token.delete()
            return Response(status=status.HTTP_200_OK)
        return Response(status=status.HTTP_400_BAD_REQUEST)


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
    last_updated = serializers.DateTimeField(default_timezone=timezone('UTC'), read_only=True)

    class Meta:
        model = Connector
        fields = ['uid', 'standard', 'format',
                  'power_type', 'max_voltage', 'max_amperage', 'max_electric_power',
                  'terms_and_conditions', 'last_updated']

    @staticmethod
    def get_max_electric_power(connector: Connector) -> str:
        # Todo: what about 1-phase and 2-phase AC?
        return connector.max_electric_power or connector.max_voltage * connector.max_amperage


class BusinessDetailsSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = BusinessDetails
        exclude = ['url']


class EvseSerializer(HyperlinkedModelSerializerCleanedUp):
    connectors = ConnectorSerializer(many=True, read_only=True)
    last_updated = serializers.DateTimeField(default_timezone=timezone('UTC'), read_only=True)

    class Meta:
        model = Evse
        fields = ['detail_url', 'uid', 'evse_id', 'status', 'last_updated', 'connectors']


class TariffSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Tariff
        fields = ('country_code', 'party_id', 'id', 'type', 'tariff_alt_url', 'elements', 'last_updated')

    id = serializers.CharField(source='uid')
    elements = serializers.SerializerMethodField()
    last_updated = serializers.DateTimeField(default_timezone=timezone('UTC'), read_only=True)

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
    last_updated = serializers.DateTimeField(default_timezone=timezone('UTC'), read_only=True)

    @staticmethod
    def get_coordinates(location: Location) -> dict:
        # Create a dict to be placed one step lower in the json
        return dict(latitude=location.latitude, longitude=location.longitude)

    @staticmethod
    def get_publish_allowed_to(location: Location) -> list:
        """
        List the token IDs of the drivers who are allowed to see this Location
        """
        return [token.uid for token in location.publish_allowed_to.all()]

    @staticmethod
    def get_facilities(location: Location):
        # Create a list of facility names
        return [facility.name for facility in location.facilities.all()]


def apply_ocpi22_query_parameters(request, queryset) -> QuerySet:
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
        tariff = get_object_or_404(Tariff, country_code=country_code, party_id=party_id, uid=uid)
        serializer = TariffSerializer(tariff, many=False)
        return Response(serializer.data)


class LocationViewSet(GenericViewSet):

    @action(methods=['GET'], detail=False)
    def locations(self, request) -> Response:
        # noinspection PyUnresolvedReferences
        queryset = apply_ocpi22_query_parameters(request, Location.objects.all())
        serializer = LocationSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)

    # Todo: How to PATCH sub-dicts of Locations
    @action(methods=['GET', 'PATCH'], detail=False,
            url_path='locations/(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def by_id(self, request, country_code, party_id, uid) -> Response:
        # noinspection PyUnresolvedReferences
        location = get_object_or_404(Location, country_code=country_code, party_id=party_id, uid=uid)

        if request.method == 'GET':
            serializer = LocationSerializer(location, context={'request': request})
            return Response(serializer.data)

        elif request.method == 'PATCH':
            serializer = LocationSerializer(location, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_400_BAD_REQUEST)

    # noinspection PyUnresolvedReferences
    queryset = Location.objects.all().order_by('id')
    serializer_class = LocationSerializer


class EvseViewSet(GenericViewSet):

    @action(methods=['GET'], detail=False)
    def evses(self, request) -> Response:
        # noinspection PyUnresolvedReferences
        queryset = apply_ocpi22_query_parameters(request, Evse.objects.all())
        serializer = EvseSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)

    @action(methods=['GET', 'PATCH'], detail=False,
            url_path='locations/(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)/(?P<evse_id>[^/.]+)')
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
    queryset = Evse.objects.all().order_by('id')
    serializer_class = EvseSerializer


class DocumentedRouter(routers.DefaultRouter):
    APIRootView = TokenAPIView


# @api_view(['GET', 'PUT'])
# def tokens(request, pk):
#     token = get_object_or_404(Token, pk=pk)
#
#     if request.method == 'GET':
#         serializer = TokenSerializer(token)
#         return Response(serializer.data)
#
#     elif request.method == 'PUT':
#         serializer = TokenSerializer(token, data=request.data)
#         if serializer.is_valid():
#             serializer.save()
#             return Response(serializer.data)
#         return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
