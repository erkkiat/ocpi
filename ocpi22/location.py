import logging

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.viewsets import GenericViewSet
from rest_framework.generics import get_object_or_404

from ocpi22.models.models import BusinessDetails, Facility, \
    Capability
from ocpi22.models.credentials import Endpoint
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.tariff import Tariff
from ocpi22.tasks import send_evse_status_update
from ocpi22.util import HyperlinkedModelSerializerCleanedUp, OCPIPaginationAndHeaders, OCPIResponse, Ocpi, NotOwner, \
    matching_operator, uid_validator
from ocpiconnector.settings import UPDATES_DISABLED


# Todo: Fetch all Locations for reliable data update, but fetch Tariffs first, since Location refers to them
# Todo: PATCH & PUT Evse
# Todo: PATCH & PUT Connector
# Todo: DELETE Tariff


class BusinessDetailsSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = BusinessDetails
        fields = ['name', 'website', 'logo']

    def to_internal_value(self, data):
        # Set all unset elements to ""
        defaults = dict(zip(self.fields, ["", "", ""]))
        defaults.update(data)
        data = defaults

        business_details, _created = BusinessDetails.objects.get_or_create(
            name=data.get('name'), website=data.get('website', ''), defaults=dict(logo=data.get('logo', ''))
        )
        return business_details

    # def to_representation(self, value):
    #     return


class ConnectorSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Connector
        fields = ['id', 'standard', 'format',
                  'power_type', 'max_voltage', 'max_amperage', 'max_electric_power',
                  'tariff_ids', 'terms_and_conditions', 'last_updated']

    id = serializers.CharField(source='uid')
    max_electric_power = serializers.SerializerMethodField()
    tariff_ids = serializers.SerializerMethodField(required=False)

    @staticmethod
    def get_tariff_ids(connector: Connector) -> list:
        return [t.uid for t in connector.tariff_ids.all()]

    @staticmethod
    def get_max_electric_power(connector: Connector) -> str:
        # Todo: what about 1-phase and 2-phase AC?
        return connector.max_electric_power or connector.max_voltage * connector.max_amperage


class TariffField(serializers.StringRelatedField):
    # noinspection PyUnresolvedReferences
    def to_internal_value(self, data):
        try:
            tariff = Tariff.objects.get(uid=data)
            return tariff
        except Tariff.DoesNotExist:
            raise ValidationError(f'Tariff with UID `{data}` does not exist in our database')

    def to_representation(self, value: Tariff):
        return value.uid


class FacilitiesSaveSerializer(serializers.StringRelatedField):
    # noinspection PyUnresolvedReferences
    def to_internal_value(self, data):
        try:
            tariff = Facility.objects.get(name=data)
            return tariff
        except Facility.DoesNotExist:
            raise ValidationError(f'`{data}` is not a valid choice for Facility in OCPI 2.2. '
                                  f'Valid choices are: {", ".join([f.name for f in Facility.objects.all()])}.')

    def to_representation(self, value: Facility):
        return value.name


class CapabilitySaveSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        # noinspection PyUnresolvedReferences
        try:
            # noinspection PyUnresolvedReferences
            c = Capability.objects.get(name=data)
            return c
        except Capability.DoesNotExist:
            # noinspection PyUnresolvedReferences
            raise ValidationError(f'Capability `{data}` is not a valid choice. '
                                  f'The options are: {", ".join([a.name for a in Capability.objects.all()])}')

    def to_representation(self, instance):
        return instance.name


class ConnectorSaveSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Connector
        fields = ['id', 'standard', 'format',
                  'power_type', 'max_voltage', 'max_amperage', 'max_electric_power',
                  'tariff_ids', 'terms_and_conditions', 'last_updated']

    id = serializers.CharField(source='uid')
    # max_electric_power = serializers.SerializerMethodField()
    tariff_ids = TariffField(many=True, required=False)


evse_validator = RegexValidator(r'[A-Z]{2}\*[A-Za-z0-9]{3}\*[E][A-Za-z0-9][A-Za-z0-9\*]{0,30}$',
                                message='OCPI evse_id has to contain a valid eMI3 EVSE-ID (NL*EVN*E123456ABCD)')


class EvseSaveSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Evse
        fields = ['uid', 'evse_id', 'status', 'last_updated', 'connectors', 'capabilities']

    connectors = ConnectorSaveSerializer(many=True, required=False)
    uid = serializers.CharField(validators=[uid_validator])
    capabilities = CapabilitySaveSerializer(many=True, required=False)
    # evse_id = serializers.CharField(required=False,
    #                                 # validators=[evse_validator],
    #                                 # label="A valid eMI3 EVSE-ID (NL*EVN*E123456ABCD)"
    #                                 )

    @staticmethod
    def process_connectors(evse: Evse, connectors: dict) -> None:
        for c in connectors:
            # noinspection PyUnresolvedReferences
            try:
                # noinspection PyUnresolvedReferences
                connector = Connector.objects.get(uid=c.get('uid'), evse=evse)
            except Connector.DoesNotExist:
                # noinspection PyUnresolvedReferences
                connector = None
            connector_serializer = ConnectorSaveSerializer(connector, data=c)
            if connector_serializer.is_valid():
                connector_serializer.save(evse=evse)

    def create(self, validated_data):
        connectors = validated_data.pop('connectors', [])
        # noinspection PyUnresolvedReferences
        evse = Evse.objects.create(**validated_data)
        self.process_connectors(evse, connectors)
        return evse

    def update(self, evse: Evse, validated_data: dict) -> Evse:
        skip_fields = ('evse_id', 'uid')

        connectors = validated_data.pop('connectors', [])
        self.process_connectors(evse, connectors)

        capabilities = validated_data.pop('capabilities', [])
        evse.capabilities.set(capabilities)

        for key, value in validated_data.items():
            if key not in skip_fields:
                setattr(evse, key, value)

        evse.save()
        return evse


class EvseSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Evse
        fields = ['detail_url', 'uid', 'evse_id', 'status', 'last_updated', 'connectors', 'capabilities']

    lookup_field = 'uid'

    connectors = ConnectorSerializer(many=True)
    uid = serializers.CharField(validators=[uid_validator])
    capabilities = CapabilitySaveSerializer(many=True, required=False)


class EvseViewSet(mixins.RetrieveModelMixin,
                  mixins.ListModelMixin,
                  GenericViewSet):
    # noinspection PyUnresolvedReferences
    queryset = Evse.objects.all().order_by('created')
    serializer_class = EvseSerializer
    pagination_class = OCPIPaginationAndHeaders

    @action(methods=['GET', 'PATCH', 'PUT'], detail=False, url_name='by-id',
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

        elif request.method in ('PATCH', 'PUT'):
            data = request.data
            readonly_fields = ('uid', 'evse_id')
            # Remove readonly fields from the incoming data
            for f in readonly_fields:
                data.pop(f, None)

            partial = request.method == 'PATCH'

            serializer = EvseSerializer(evse, data=data, partial=partial, context={'request': request})
            if serializer.is_valid():
                serializer.save()
                return OCPIResponse(serializer.data)
            else:
                return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST,
                                    status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

        return OCPIResponse(http_status=status.HTTP_400_BAD_REQUEST,
                            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)


class Coordinate(serializers.CharField):
    def to_representation(self, value):
        """
        OCPI standard requires coordinates in string format with six decimals
        >>> c = Coordinate()
        >>> c.to_representation(60)
        '60.000000'
        """
        return f"{float(value):.6f}"


class CoordinatesSaveSerializer(serializers.Serializer):
    def update(self, instance, validated_data):
        pass

    def create(self, validated_data):
        pass

    latitude = Coordinate()
    longitude = Coordinate()


class LocationSerializerBase(serializers.Serializer):

    id = serializers.CharField(source='uid')
    operator = BusinessDetailsSerializer(required=False, many=False)
    suboperator = BusinessDetailsSerializer(required=False, many=False)
    owner = BusinessDetailsSerializer(required=False, many=False)

    def update(self, instance, validated_data):
        pass

    def create(self, validated_data):
        pass




class LocationSerializer(LocationSerializerBase, HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Location
        fields = ['detail_url', 'country_code', 'party_id', 'id', 'publish', 'publish_allowed_to',
                  'name', 'address', 'city', 'postal_code', 'state', 'country',
                  'coordinates', 'parking_type', 'evses',
                  'operator', 'suboperator', 'owner',
                  'facilities', 'time_zone', 'last_updated']

    lookup_field = 'uid'

    coordinates = CoordinatesSaveSerializer(source='*')
    evses = EvseSerializer(many=True, required=False)
    publish_allowed_to = serializers.SerializerMethodField()
    facilities = FacilitiesSaveSerializer()

    # noinspection PyUnresolvedReferences
    # def create(self, validated_data: dict, *args, **kwargs):
    #     ic('create', validated_data)
    #     evses = validated_data.pop('evses', [])
    #     location = Location.objects.create(**validated_data)
    #     for evse_dict in evses:
    #         connectors = evse_dict.pop('connectors', [])
    #         evse = Evse.objects.create(location=location, **evse_dict)
    #         for connector_dict in connectors:
    #             Connector.objects.create(evse=evse, **connector_dict)
    #     return location

    # noinspection PyUnresolvedReferences
    # def update(self, location, validated_data, *args, **kwargs):
    #     evses = validated_data.pop('evses', [])
    #     Location.objects.filter(uid=location.uid).update(**validated_data)
    #     for evse_dict in evses:
    #         connectors = evse_dict.pop('connectors', [])
    #         evse, created = Evse.objects.get_or_create(location=location, uid=evse_dict.pop('uid'),
    #                                                    defaults=evse_dict)
    #         if not created:
    #             Evse.objects.filter(uid=evse.uid).update(**evse_dict)
    #         for connector_dict in connectors:
    #             connector, created = Connector.objects.get_or_create(evse=evse,
    #                                                                  uid=connector_dict.pop('uid'),
    #                                                                  defaults=connector_dict)
    #             if not created:
    #                 Connector.objects.filter(uid=connector.uid).update(**connector_dict)
    #     return location

    @staticmethod
    def get_coordinates(location: Location) -> dict:
        # Create a dict to be placed inside the Location json
        # Longitude/Latitude has to be a string (OCPI) and have a fixed length of 6 decimals (e-clearing.net)
        return dict(latitude=f'{location.latitude:.6f}', longitude=f'{location.longitude:.6f}')

    # @staticmethod
    # def put_coordinates(data) -> None:
    #     ic(data.coordinates)

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


class LocationSaveSerializer(LocationSerializerBase, HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Location
        fields = ['country_code', 'party_id', 'id', 'publish',
                  # 'publish_allowed_to',
                  'name', 'address', 'city', 'postal_code', 'state', 'country',
                  'coordinates', 'parking_type',
                  'evses',
                  'operator', 'suboperator', 'owner',
                  'facilities',
                  'time_zone', 'last_updated']

    lookup_field = 'uid'

    id = serializers.CharField(source='uid')
    evses = EvseSaveSerializer(many=True, required=False)
    coordinates = CoordinatesSaveSerializer()
    name = serializers.CharField(required=False)
    facilities = FacilitiesSaveSerializer(many=True, required=False)
    owner = BusinessDetailsSerializer(required=False)
    operator = BusinessDetailsSerializer(required=False)
    suboperator = BusinessDetailsSerializer(required=False)

    @staticmethod
    def process_coordinates(validated_data: dict):
        """Handle manually all subobjects the Location cannot handle"""
        coordinates = validated_data.pop('coordinates', None)
        if coordinates:
            validated_data['latitude'] = coordinates.get('latitude')
            validated_data['longitude'] = coordinates.get('longitude')
        return validated_data

    def create(self, validated_data: dict):
        with transaction.atomic():
            # Pop out all elements which are not directly understood by Location, and process them separately
            validated_data = self.process_coordinates(validated_data)
            facilities = validated_data.pop('facilities', None)
            evses = validated_data.pop('evses', [])

            # noinspection PyUnresolvedReferences
            location = Location.objects.create(**validated_data)

            for e in evses:
                connectors = e.pop('connectors', [])
                capabilities = e.pop('capabilities', [])

                # noinspection PyUnresolvedReferences
                evse = Evse.objects.create(**e, location=location)

                # Capabilities
                evse.capabilities.set(capabilities)

                # Connectors
                for c in connectors:
                    tariff_ids = c.pop('tariff_ids', [])
                    # noinspection PyUnresolvedReferences
                    connector = Connector.objects.create(**c, evse=evse)

                    # Tariffs
                    tariffs = []
                    for t in tariff_ids:
                        # noinspection PyUnresolvedReferences
                        try:
                            # noinspection PyUnresolvedReferences
                            tariff = Tariff.objects.get(uid=t,
                                                        country_code=location.country_code,
                                                        party_id=location.party_id)
                            tariffs.append(tariff)
                        except Tariff.DoesNotExist:
                            raise ValidationError(f"Tariff `{t}` for {location.country_code}*{location.party_id} "
                                                  "does not exist in our database")
                    connector.tariff_ids.set(tariffs)
            if facilities:
                location.facilities.set(facilities)
            return location

    def update(self, location: Location, validated_data: dict) -> Location:
        readonly_fields = ('country_code', 'party_id', 'uid')

        # Pop out all elements which are not directly understood by Location, and process them separately
        validated_data = self.process_coordinates(validated_data)
        evses = validated_data.pop('evses', [])
        facilities = validated_data.pop('facilities', [])
        location.facilities.set(facilities)

        for key, value in validated_data.items():
            if key not in readonly_fields:
                setattr(location, key, value)

        location.save()

        for e in evses:
            connectors = e.pop('connectors', [])
            capabilities = e.pop('capabilities', [])
            # noinspection PyUnresolvedReferences
            try:
                # noinspection PyUnresolvedReferences
                evse = Evse.objects.get(uid=e.get('uid'), location=location)
                for key, value in e.items():
                    if key not in ('uid', 'evse_id'):
                        setattr(evse, key, value)
                evse.save()
            except Evse.DoesNotExist:
                # noinspection PyUnresolvedReferences
                evse = Evse.objects.create(**e, location=location)
            evse.capabilities.set(capabilities)

            for c in connectors:
                # noinspection PyUnresolvedReferences
                tariff_ids = c.pop('tariff_ids', [])
                # noinspection PyUnresolvedReferences
                try:
                    # noinspection PyUnresolvedReferences
                    connector = Connector.objects.get(uid=c.get('uid'), evse=evse)
                    for key, value in c.items():
                        if key not in ['uid']:
                            setattr(connector, key, value)
                    connector.save()
                except Connector.DoesNotExist:
                    # noinspection PyUnresolvedReferences
                    connector = Connector.objects.create(**c, evse=evse)
                connector.tariff_ids.set(tariff_ids)

        return location


class LocationViewSet(mixins.ListModelMixin,
                      GenericViewSet):
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['country_code', 'party_id', 'parking_type', 'city', 'publish', 'facilities', 'country']
    pagination_class = OCPIPaginationAndHeaders
    root_view_name = 'locations'

    lookup_field = "uid"

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'Location {self.kwargs.get("uid")}'
        if self.name:
            return f'{self.name.capitalize()}'
        return 'Locations'

    @transaction.atomic
    @action(methods=['GET', 'PATCH', 'PUT'], detail=False, url_name='by-evse-id',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)/(?P<evse_id>[^/.]+)')
    def by_evse_id(self, request, country_code, party_id, uid, evse_id) -> OCPIResponse:
        # noinspection PyUnresolvedReferences
        evse = get_object_or_404(Evse, uid=evse_id, location__uid=uid)
        location = evse.location

        if location.party_id != party_id or location.country_code != country_code:
            return OCPIResponse(
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                status_message='The EVSE is not owned by the specified party or is not in the specified country')

        if request.method == 'GET':
            serializer = EvseSerializer(evse, context={'request': request})
            return OCPIResponse(serializer.data)

        elif request.method in ('PATCH', 'PUT'):
            data = request.data
            readonly_fields = ['evse_id']
            # Remove readonly fields from the incoming data
            for f in readonly_fields:
                data.pop(f, None)

            data.update(dict(uid=evse_id, country_code=country_code, party_id=party_id))

            partial = request.method == 'PATCH'

            serializer = EvseSaveSerializer(evse, data=data, partial=partial, context={'request': request})
            if serializer.is_valid():
                serializer.save()
                return OCPIResponse(serializer.data)
            else:
                return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST,
                                    status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

        return OCPIResponse(http_status=status.HTTP_400_BAD_REQUEST,
                            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    @transaction.atomic
    def put(self, request, *_args, **_kwargs):
        data = request.data.get('data', request.data)
        # print(data)
        uid = data.get('id')
        country_code = request.data.get('country_code')
        party_id = request.data.get('party_id')

        if not matching_operator(request, country_code, party_id):
            return NotOwner()

        if uid:
            # noinspection PyUnresolvedReferences
            try:
                # noinspection PyUnresolvedReferences
                location = Location.objects.get(uid=uid, country_code=country_code, party_id=party_id)
            except Location.DoesNotExist:
                # print(f"New location {uid}, {country_code}, {party_id}")
                location = None
            serializer = LocationSaveSerializer(location, data=data)
            if serializer.is_valid():
                serializer.save()
                http_status = status.HTTP_200_OK if location else status.HTTP_201_CREATED
                return OCPIResponse(serializer.data, http_status=http_status)
            else:
                return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST,
                                    status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)
        else:
            return OCPIResponse(
                status_message=f'Country code, party_id and id are required when doing a PUT for a Location.',
                http_status=status.HTTP_400_BAD_REQUEST,
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    # @action(methods=['GET', 'PATCH'], detail=False,
    #         url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)/(?P<evse_uid>[^/.]+)')
    # def by_evse_id(self, request: Request, country_code, party_id, uid, evse_uid, partial=True) -> OCPIResponse:
    #     if request.method != 'GET' and not hasattr(request, 'credentials'):
    #         return OCPIResponse('Credentials are needed for creating Locations.',
    #                             status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
    #                             http_status=status.HTTP_403_FORBIDDEN)
    #     location = get_object_or_404(Location, uid=uid, party_id=party_id, country_code=country_code)
    #     evse = get_object_or_404(Evse, uid=evse_uid, location=location)
    #     if request.method == 'PATCH':
    #         print(f'*** Updating Evse {evse_uid} with new status {request.data.get("status")} '
    #               f'from {request.credentials.party()}')
    #         serializer = EvseSerializer(instance=evse, data=request.data, partial=partial)
    #         if serializer.is_valid():
    #             serializer.save()
    #         else:
    #             return OCPIResponse(serializer.errors, http_status=status.HTTP_400_BAD_REQUEST,
    #                                 status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)
    #     else:
    #         serializer = EvseSerializer(instance=evse)
    #     return OCPIResponse(serializer.data)

    @transaction.atomic
    @action(methods=['GET', 'PUT', 'PATCH'], detail=False, url_name='by-id',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def location_by_id(self, request: Request, country_code, party_id, uid) -> OCPIResponse:
        # noinspection PyUnresolvedReferences
        location = get_object_or_404(Location,
                                     country_code=country_code,
                                     party_id=party_id,
                                     uid=uid)
        serializer = LocationSerializer(location, context={'request': request})
        if request.method == 'GET':
            return OCPIResponse(serializer.data)

        elif request.method in ('PUT', 'PATCH'):
            partial = request.method == 'PATCH'

            serializer = LocationSaveSerializer(location,
                                            data=request.data.get('data', request.data),
                                            partial=partial,
                                            context={'request': request})
            if serializer.is_valid():
                serializer.save()
                return OCPIResponse(serializer.data)
            else:
                return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST,
                                    status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

        return OCPIResponse(http_status=status.HTTP_400_BAD_REQUEST,
                            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    # noinspection PyUnresolvedReferences
    queryset = Location.objects.all().order_by('created')
    serializer_class = LocationSerializer


def send_evse_updates(evse_uid):
    """
    Find all endpoints interested in Location updates and send update in a background task
    """

    if settings.SEND_UPDATES:
        # noinspection PyUnresolvedReferences
        endpoints = Endpoint.objects.filter(identifier='locations', role='RECEIVER')
        e: Endpoint
        for e in endpoints:
            print(f'Send EVSE update to {e.url}')
            if settings.BACKGROUND_SEND:
                send_evse_status_update.delay(evse_uid, e.pk)
            else:
                send_evse_status_update(evse_uid, e.pk)
    else:
        logging.warning(UPDATES_DISABLED)
