from django.conf import settings
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from ocpi22.choices import OcpiModuleEnum
from ocpi22.models.business_details import BusinessDetails
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.location import Connector, Evse, Location
from ocpi22.models.models import Facility, Capability
from ocpi22.models.tariff import Tariff
from ocpi22.models.token import Token
from ocpi22.ocpi.util import Ocpi
from ocpi22.util import uid_validator, fetch_object
from ocpi22.serializers import HyperlinkedModelSerializerCleanedUp, UTCDateTimeField
from ocpiconnector.ocpi_identities import Party


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


class PowerTypeSerializer(serializers.CharField):
    def to_representation(self, power_type):
        version = self.context.get('version', None)  # Action required only for OCPI 2.2
        if version == '2.2':
            power_type = dict(
                AC_2_PHASE='AC_1_PHASE',
                AC_2_PHASE_SPLIT='AC_1_PHASE',
            ).get(power_type, power_type)
        return power_type


class TariffField(serializers.StringRelatedField):
    def to_internal_value(self, data):
        try:
            request = self.context.get('request')
            role = request.credentialsrole
            tariff = Tariff.objects.get(uid__iexact=data, archived=False, ocpi_master=role)
            return tariff
        except Tariff.DoesNotExist as e:
            credentials = self.context.get('credentials')
            if credentials:
                if fetch_object(uid=data, ocpi_module=OcpiModuleEnum.TARIFFS, credentials=credentials):
                    return self.to_internal_value(data)
            raise ValidationError(f'Tariff with UID `{data}` cannot be fetched: {e}')
        except Tariff.MultipleObjectsReturned as e:
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


class CapabilitySerializer(serializers.Serializer):
    def to_internal_value(self, data):
        try:
            c = Capability.objects.get(name=data)
            return c
        except Capability.DoesNotExist:
            raise ValidationError(f'Capability `{data}` is not a valid choice. '
                                  f'The options are: {", ".join([a.name for a in Capability.objects.all()])}')

    def to_representation(self, instance):
        return instance.name


class MaxElectricPowerSerializer(serializers.IntegerField):
    def to_representation(self, connector):
        assert isinstance(connector, Connector)  # Must use source='*'
        phases = Ocpi.POWERTYPE_PHASES.get(connector.power_type, 1)
        return connector.max_electric_power or connector.max_voltage * connector.max_amperage * phases

    def to_internal_value(self, data):
        return dict(max_electric_power=data)


class ConnectorSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Connector
        fields = ['id', 'standard', 'format',
                  'power_type', 'max_voltage', 'max_amperage', 'max_electric_power',
                  'tariff_ids', 'terms_and_conditions', 'last_updated']

    id = serializers.CharField(source='uid')
    tariff_ids = TariffField(many=True, required=False)
    last_updated = UTCDateTimeField(required=False)
    power_type = PowerTypeSerializer()
    max_electric_power = MaxElectricPowerSerializer(source='*', required=False)


class EvseSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Evse
        fields = ['detail_url', 'uid', 'evse_id', 'status', 'last_updated', 'connectors', 'capabilities']

    lookup_field = 'uid'

    connectors = ConnectorSerializer(many=True, required=False)
    uid = serializers.CharField(validators=[uid_validator])
    capabilities = CapabilitySerializer(many=True, required=False)
    last_updated = UTCDateTimeField(required=False)

    def to_representation(self, evse: Evse):
        result = super().to_representation(evse)
        version = self.context.get('version', None)
        if version == '2.2' and 'capabilities' in result:
            try:
                result['capabilities'].remove('START_SESSION_CONNECTOR_REQUIRED')  # Not supported in OCPI 2.2
            except ValueError:
                pass  # Ok, no such capability in this EVSE anyway
        return result

    @staticmethod
    def process_connectors(evse: Evse, connectors: dict) -> None:
        for c in connectors:
            tariff_ids = c.pop('tariff_ids', [])
            try:
                connector = Connector.objects.get(uid=c.get('uid'), evse=evse)
                for key, value in c.items():
                    if key != 'uid':
                        setattr(connector, key, value)
                connector.tariff_ids.set(tariff_ids)
                connector.save()
            except Connector.DoesNotExist:
                connector = Connector.objects.create(evse=evse, **c)
                connector.tariff_ids.set(tariff_ids)

    def create(self, validated_data):
        connectors = validated_data.pop('connectors', [])
        capabilities = validated_data.pop('capabilities', [])
        evse = Evse.objects.create(**validated_data)
        evse.capabilities.set(capabilities)
        self.process_connectors(evse, connectors)
        return evse

    def update(self, evse: Evse, validated_data: dict) -> Evse:
        skip_fields = {'evse_id', 'uid'}

        connectors = validated_data.pop('connectors', [])
        self.process_connectors(evse, connectors)

        capabilities = validated_data.pop('capabilities', [])
        evse.capabilities.set(capabilities)

        for key, value in validated_data.items():
            if key not in skip_fields:
                setattr(evse, key, value)

        evse.save()
        return evse


class Coordinate(serializers.CharField):
    def to_representation(self, value):
        """
        OCPI standard requires coordinates in string format with six decimals
        >>> c = Coordinate()
        >>> c.to_representation(60)
        '60.000000'
        """
        return f"{float(value):.6f}"


class CoordinatesSerializer(serializers.Serializer):
    latitude = Coordinate()
    longitude = Coordinate()


class PublishAllowedToSerializer(serializers.Serializer):
    def to_internal_value(self, data) -> Token:
        token = Token.get_if_exists(**data)
        if not token:
            raise ValidationError(f'Unable to find token with {str(data)}. Try to send the Token to us first.')
        return token

    def to_representation(self, token: Token) -> dict:
        return dict(uid=token.uid, issuer=token.issuer)


class LocationSerializer221(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Location
        fields = ['detail_url', 'country_code', 'party_id', 'id', 'publish',
                  'publish_allowed_to',
                  'name', 'address', 'city', 'postal_code', 'state', 'country',
                  'coordinates', 'parking_type',
                  'evses',
                  'operator', 'suboperator', 'owner',
                  'facilities',
                  'time_zone', 'last_updated']

    lookup_field = 'uid'

    id = serializers.CharField(source='uid')
    country_code = serializers.CharField(source='ocpi_master.country_code')
    party_id = serializers.CharField(source='ocpi_master.party_id')

    evses = EvseSerializer(many=True, required=False)
    coordinates = CoordinatesSerializer()
    name = serializers.CharField(required=False)
    facilities = FacilitiesSaveSerializer(many=True, required=False)
    owner = BusinessDetailsSerializer(required=False)
    operator = BusinessDetailsSerializer(required=False)
    suboperator = BusinessDetailsSerializer(required=False)
    last_updated = UTCDateTimeField(required=False)
    publish_allowed_to = PublishAllowedToSerializer(many=True, required=False)

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
            publish_allowed_to = validated_data.pop('publish_allowed_to', [])

            location = Location.objects.create(**validated_data)
            location.publish_allowed_to.set(publish_allowed_to)

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
                                                        ocpi_master__country_code=location.ocpi_master.country_code,
                                                        ocpi_master__party_id=location.ocpi_master.party_id,
                                                        archived=False)
                            tariffs.append(tariff)
                        except Tariff.DoesNotExist:
                            # Todo: Fetch Tariffs from other party
                            raise ValidationError(
                                f"Tariff `{t}` for {location.ocpi_master.country_code}*"
                                f"{location.ocpi_master.party_id} does not exist in our database")
                    connector.tariff_ids.set(tariffs)
            if facilities:
                location.facilities.set(facilities)
            return location

    def update(self, location: Location, validated_data: dict) -> Location:
        readonly_fields = {'country_code', 'party_id', 'uid'}  # Lookups in set are faster

        # Pop out all elements which are not directly understood by Location, and process them separately
        validated_data = self.process_coordinates(validated_data)
        evses = validated_data.pop('evses', [])
        facilities = validated_data.pop('facilities', [])
        publish_allowed_to = validated_data.pop('publish_allowed_to', [])

        location.facilities.set(facilities)
        location.publish_allowed_to.set(publish_allowed_to)

        for key, value in validated_data.items():
            if key not in readonly_fields:
                setattr(location, key, value)

        location.save()

        for e in evses:
            connectors = e.pop('connectors', [])
            capabilities = e.pop('capabilities', [])
            try:
                evse = Evse.objects.get(uid=e.get('uid'), location=location)
                for key, value in e.items():
                    if key not in {'uid', 'evse_id'}:
                        setattr(evse, key, value)
                evse.save()
            except Evse.DoesNotExist:
                evse = Evse.objects.create(**e, location=location)
            evse.capabilities.set(capabilities)

            for c in connectors:
                tariff_ids = c.pop('tariff_ids', [])
                try:
                    connector = Connector.objects.get(uid=c.get('uid'), evse=evse)
                    for key, value in c.items():
                        if key != 'uid':
                            setattr(connector, key, value)
                    connector.save()
                except Connector.DoesNotExist:
                    connector = Connector.objects.create(**c, evse=evse)
                connector.tariff_ids.set(tariff_ids)

        return location


class LocationSerializer(LocationSerializer221):
    class Meta:
        model = Location
        fields = ['detail_url', 'country_code', 'party_id', 'id', 'publish', 'publish_allowed_to',
                  'name', 'address', 'city', 'postal_code', 'country',
                  'coordinates', 'parking_type', 'evses',
                  'operator', 'suboperator', 'owner',
                  'facilities', 'time_zone', 'last_updated']
