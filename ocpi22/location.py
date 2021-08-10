from django_filters.rest_framework import DjangoFilterBackend
from icecream import ic
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.viewsets import GenericViewSet
from rest_framework.generics import get_object_or_404

from ocpi22.models import Location, Evse, Connector, BusinessDetails, uid_validator, Endpoint
from ocpi22.tasks import send_location_update, send_evse_status_update
from ocpi22.util import HyperlinkedModelSerializerCleanedUp, OCPIPaginationAndHeaders, OCPIResponse, Ocpi


class BusinessDetailsSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = BusinessDetails
        fields = ['name', 'website', 'logo']


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
    def get_tariff_ids(connector: Connector) -> list:
        return [t.uid for t in connector.tariff_ids.all()]

    @staticmethod
    def get_max_electric_power(connector: Connector) -> str:
        # Todo: what about 1-phase and 2-phase AC?
        return connector.max_electric_power or connector.max_voltage * connector.max_amperage


class EvseSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Evse
        fields = ['detail_url', 'uid', 'evse_id', 'status', 'last_updated', 'connectors']

    connectors = ConnectorSerializer(many=True)
    uid = serializers.CharField(validators=[uid_validator])

    # def create(self, *args, **kwargs):
    #     ic()
    #     raise Exception('Create not implemented')
    #
    # def update(self, *args, **kwargs):
    #     ic()
    #     raise Exception('Update not implemented')


class EvseViewSet(mixins.RetrieveModelMixin,
                  mixins.ListModelMixin,
                  GenericViewSet):
    # noinspection PyUnresolvedReferences
    queryset = Evse.objects.all().order_by('created')
    serializer_class = EvseSerializer
    pagination_class = OCPIPaginationAndHeaders

    @action(methods=['GET'], detail=False, url_name='by-id',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)/(?P<evse_id>[^/.]+)')
    def evse_by_id(self, request, country_code, party_id, uid, evse_id) -> OCPIResponse:
        # noinspection PyUnresolvedReferences
        evse = get_object_or_404(Evse, uid=evse_id)
        location = evse.location
        if location.uid != uid or location.party_id != party_id or location.country_code != country_code:
            return OCPIResponse(
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                status_message='The EVSE is not owned by the specified party or is not in the specified country')

        if request.method == 'GET':
            serializer = EvseSerializer(evse, context={'request': request})
            return OCPIResponse(serializer.data)

        # elif request.method == 'PATCH':
        #     serializer = EvseSerializer(evse, data=request.data, partial=True, context={'request': request})
        #     if serializer.is_valid():
        #         serializer.save()
        #         return Response(serializer.data)
        #     else:
        #         return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return OCPIResponse(http_status=status.HTTP_400_BAD_REQUEST)


class LocationSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Location
        fields = ['detail_url', 'country_code', 'party_id', 'id', 'publish', 'publish_allowed_to',
                  'name', 'address', 'city', 'postal_code', 'state', 'country',
                  'coordinates', 'parking_type', 'evses',
                  'operator', 'suboperator', 'owner',
                  'facilities', 'time_zone', 'last_updated']

    lookup_field = 'uid'

    id = serializers.CharField(source='uid')
    coordinates = serializers.SerializerMethodField()
    evses = EvseSerializer(many=True)
    operator = BusinessDetailsSerializer(read_only=True, many=False)
    suboperator = BusinessDetailsSerializer(read_only=True, many=False)
    owner = BusinessDetailsSerializer(read_only=True, many=False)
    publish_allowed_to = serializers.SerializerMethodField()
    facilities = serializers.SerializerMethodField()

    # noinspection PyUnresolvedReferences
    def create(self, validated_data, *args, **kwargs):
        ic('create', validated_data)
        evses = validated_data.pop('evses', [])
        location = Location.objects.create(**validated_data)
        for evse_dict in evses:
            connectors = evse_dict.pop('connectors', [])
            evse = Evse.objects.create(location=location, **evse_dict)
            for connector_dict in connectors:
                Connector.objects.create(evse=evse, **connector_dict)
        return location

    # noinspection PyUnresolvedReferences
    def update(self, location, validated_data, *args, **kwargs):
        ic('update', location, validated_data)
        evses = validated_data.pop('evses') if 'evses' in validated_data else []
        Location.objects.filter(uid=location.uid).update(**validated_data)
        for evse_dict in evses:
            connectors = evse_dict.pop('connectors') if 'connectors' in evse_dict else []
            evse, created = Evse.objects.get_or_create(location=location, uid=evse_dict.pop('uid'),
                                                       defaults=evse_dict)
            if not created:
                Evse.objects.filter(uid=evse.uid).update(**evse_dict)
            for connector_dict in connectors:
                connector, created = Connector.objects.get_or_create(evse=evse,
                                                                     uid=connector_dict.pop('uid'),
                                                                     defaults=connector_dict)
                if not created:
                    Connector.objects.filter(uid=connector.uid).update(**connector_dict)
        return location

    @staticmethod
    def get_coordinates(location: Location) -> dict:
        # Create a dict to be placed one step lower in the json
        # Longitude/Latitude has to be a string (OCPI) and have a fixed length of 6 decimals (e-clearing.net)
        return dict(latitude=f'{location.latitude:.6f}', longitude=f'{location.longitude:.6f}')

    @staticmethod
    def put_coordinates(data) -> None:
        ic(data.coordinates)

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


class LocationViewSet(mixins.ListModelMixin,
                      mixins.RetrieveModelMixin,
                      GenericViewSet):
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['country_code', 'party_id', 'parking_type', 'city', 'publish', 'facilities', 'country']
    pagination_class = OCPIPaginationAndHeaders
    root_view_name = 'locations'

    def get_view_name(self):
        return 'Locations'

    # noinspection PyUnresolvedReferences
    def put(self, request, country_code=None, party_id=None, uid=None, evse_uid=None):
        ic()
        if evse_uid:
            self.by_evse_id(request, country_code, party_id, uid, evse_uid, partial=False)

        ic(country_code, party_id, uid, evse_uid)
        data = request.data.get('data', request.data)
        if uid:
            # Write over an existing Location
            location: Location = get_object_or_404(Location,
                                                   country_code=country_code,
                                                   party_id=party_id,
                                                   uid=uid)
            serializer = self.get_serializer(location, data=data)
            ic('Writing over', serializer)
        else:
            # Create a new object
            # This relies on serializer.create()
            serializer = self.get_serializer(data=data)

        if serializer.is_valid():
            serializer.save()
            location: Location = get_object_or_404(Location, uid=uid)
            serializer = self.get_serializer(location)
            ic(serializer.data)
            return OCPIResponse(serializer.data)
        else:
            ic('Not valid', serializer.data)
            return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST)

    @action(methods=['GET', 'PATCH'], detail=False,
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)/(?P<evse_uid>[^/.]+)')
    def by_evse_id(self, request: Request, country_code, party_id, uid, evse_uid, partial=True) -> OCPIResponse:
        ic()
        location = get_object_or_404(Location, uid=uid, party_id=party_id, country_code=country_code)
        evse = get_object_or_404(Evse, uid=evse_uid, location=location)
        if request.method == 'PATCH':
            serializer = EvseSerializer(instance=evse, data=request.data, partial=partial)
            if serializer.is_valid():
                serializer.save()
            else:
                return OCPIResponse(serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
        else:
            serializer = EvseSerializer(instance=evse)
        return OCPIResponse(serializer.data)

    # Todo: How to PATCH sub-dicts of Locations
    @action(methods=['GET', 'PUT', 'PATCH'], detail=False,
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def by_id(self, request: Request, country_code, party_id, uid) -> OCPIResponse:
        if request.method == 'GET':
            # noinspection PyUnresolvedReferences
            location = get_object_or_404(Location,
                                         country_code=country_code,
                                         party_id=party_id,
                                         uid=uid)
            serializer = LocationSerializer(location, context={'request': request})
            return OCPIResponse(serializer.data)

        elif request.method in ('PUT', 'PATCH'):
            partial = request.method == 'PATCH'
            serializer = LocationSerializer(data=request.data.get('data', request.data),
                                            context={'request': request})
            if not serializer.is_valid():
                return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST)

            # noinspection PyUnresolvedReferences
            location, created = Location.objects.get_or_create(
                country_code=country_code,
                party_id=party_id,
                uid=uid,
                defaults=serializer.data
            )
            if created:
                return OCPIResponse(serializer.data)

            serializer = LocationSerializer(location,
                                            data=request.data.get('data', request.data),
                                            partial=partial,
                                            context={'request': request})
            if serializer.is_valid():
                serializer.save()
                return OCPIResponse(serializer.data)
            else:
                return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST)

        return OCPIResponse(http_status=status.HTTP_400_BAD_REQUEST)

    # noinspection PyUnresolvedReferences
    queryset = Location.objects.all().order_by('created')
    serializer_class = LocationSerializer


def send_evse_updates(evse_uid):
    """
    Find all endpoints interested in Location updates and send update in a background task
    """

    # noinspection PyUnresolvedReferences
    endpoints = Endpoint.objects.filter(identifier='locations', role='RECEIVER')
    e: Endpoint
    for e in endpoints:
        print(f'Send EVSE update to {e.url}')
        send_evse_status_update.delay(evse_uid, e.pk)


def send_location_updates(location_uid):
    """
    Find all endpoints interested in Location updates and send update in a background task
    """

    # noinspection PyUnresolvedReferences
    endpoints = Endpoint.objects.filter(identifier='locations', role='RECEIVER')
    e: Endpoint
    for e in endpoints:
        print(f'Send Location update to {e.url}')
        send_location_update.delay(location_uid, e.pk)
