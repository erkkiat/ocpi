from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from ocpi22.models.business_details import BusinessDetails
from ocpi22.models.location import Connector, Evse, Location
from ocpi22.models.models import Facility, Capability
from ocpi22.models.tariff import Tariff
from ocpi22.util import uid_validator
from ocpi22.serializers import HyperlinkedModelSerializerCleanedUp


class BusinessDetailsSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = BusinessDetails
        fields = ['name', 'website', 'logo']

    def create(self, data):
        if isinstance(data, BusinessDetails):
            return data

        # Set all unset elements to ""
        defaults = dict(zip(self.fields, ["", "", ""]))
        defaults.update(data)
        data = defaults

        business_details, _created = BusinessDetails.objects.get_or_create(
            name=data.get('name'), website=data.get('website', ''), defaults=dict(logo=data.get('logo', ''))
        )
        return business_details

    def to_internal_value(self, data):
        return self.create(data)


class ConnectorSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Connector
        fields = ['id', 'standard', 'format',
                  'power_type', 'max_voltage', 'max_amperage', 'max_electric_power',
                  'tariff_ids', 'terms_and_conditions', 'last_updated']

    id = serializers.CharField(source='uid')
    max_electric_power = serializers.SerializerMethodField()
    tariff_ids = serializers.SerializerMethodField(required=False)
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)

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
            tariff = Tariff.objects.get(uid=data, archived=False)
            return tariff
        except (Tariff.DoesNotExist, Tariff.MultipleObjectsReturned) as e:
            raise ValidationError(f'Tariff with UID `{data}` cannot be fetched: {e}')

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
    tariff_ids = TariffField(many=True, required=False)
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)


class EvseSaveSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Evse
        fields = ['uid', 'evse_id', 'status', 'last_updated', 'connectors', 'capabilities']

    connectors = ConnectorSaveSerializer(many=True, required=False)
    uid = serializers.CharField(validators=[uid_validator])
    capabilities = CapabilitySaveSerializer(many=True, required=False)
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)

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
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)


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
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)

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
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)

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

            location = Location.objects.create(**validated_data)

            for e in evses:
                connectors = e.pop('connectors', [])
                capabilities = e.pop('capabilities', [])

                evse = Evse.objects.create(**e, location=location)

                # Capabilities
                evse.capabilities.set(capabilities)

                # Connectors
                for c in connectors:
                    tariff_ids = c.pop('tariff_ids', [])
                    connector = Connector.objects.create(**c, evse=evse)

                    # Tariffs
                    tariffs = []
                    for t in tariff_ids:
                        try:
                            tariff = Tariff.objects.get(uid=t,
                                                        country_code=location.country_code,
                                                        party_id=location.party_id,
                                                        archived=False)
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
