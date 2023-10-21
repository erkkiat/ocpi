from typing import Union

from django.conf import settings
from django.db import IntegrityError
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from ocpi22 import choices
from ocpi22.choices import TOKEN_TYPE_CHOICES, CONNECTION_STATUS_CHOICES, OcpiRolesEnum
from util import default_error_messages
from ocpi22.locations.serializers import BusinessDetailsSerializer, Coordinate
from ocpi22.models.cdr import Cdr
from ocpi22.models.credentials import CredentialsRole, Credentials
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session, ChargingPeriod, CdrDimension, ChargingPeriodSerializer, TotalCostSerializer
from ocpi22.models.tariff import PriceComponent, TariffElement, Tariff
from ocpi22.models.token import Token
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.serializers import SerializerCleanedUp, HyperlinkedModelSerializerCleanedUp, UTCDateTimeField
from ocpi22.util import base64_to_ascii, CiStringChoiceField, MultipleChoiceFieldList, CiStringField
from ocpiconnector.ocpi_identities import Party


class CdrTokenSerializer(SerializerCleanedUp):
    uid = serializers.CharField(required=True, source='cdr_token_uid')
    type = serializers.ChoiceField(choices=TOKEN_TYPE_CHOICES, required=True, source='cdr_token_type')
    contract_id = serializers.CharField(required=True, source='cdr_token_contract_id')


class TokenSerializer(HyperlinkedModelSerializerCleanedUp):
    default_error_messages = default_error_messages

    class Meta:
        model = Token
        fields = ['detail_url', 'country_code', 'party_id', 'uid', 'type',
                  'contract_id', 'visual_number', 'issuer', 'group_id',
                  'valid', 'whitelist', 'language', 'default_profile_type', 'last_updated']

    country_code = CiStringField(source='ocpi_master.country_code')
    party_id = CiStringField(source='ocpi_master.party_id')

    whitelist = CiStringChoiceField(required=False, choices=Token.WHITELIST_CHOICES)
    default_profile_type = CiStringChoiceField(required=False, choices=Token.PROFILE_TYPE_CHOICES)
    language = CiStringChoiceField(required=False, default='EN', choices=choices.LANGUAGE_CHOICES)
    type = CiStringChoiceField(required=False, choices=choices.TOKEN_TYPE_CHOICES)
    last_updated = UTCDateTimeField(required=False)


class PriceComponentSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = PriceComponent
        fields = ('type', 'price', 'vat', 'step_size')

    step_size = serializers.IntegerField(min_value=0)


class RestrictionSerializer(SerializerCleanedUp):
    start_time = serializers.TimeField(required=False)
    end_time = serializers.TimeField(required=False)

    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)

    min_kwh = serializers.FloatField(required=False)
    max_kwh = serializers.FloatField(required=False)

    min_current = serializers.FloatField(required=False)
    max_current = serializers.FloatField(required=False)

    min_power = serializers.FloatField(required=False)
    max_power = serializers.FloatField(required=False)

    min_duration = serializers.IntegerField(required=False)
    max_duration = serializers.IntegerField(required=False)

    day_of_week = MultipleChoiceFieldList(choices=choices.DAY_OF_WEEK_CHOICES, required=False)
    reservation = serializers.ChoiceField(choices=choices.RESERVATION_CHOICES, required=False)


class ElementsSerializer(SerializerCleanedUp):
    price_components = PriceComponentSerializer(
        many=True,
        help_text=f'See {settings.OCPI_SPECIFICATION_URL}mod_tariffs.asciidoc'
                  f'#mod_tariffs_pricecomponent_class'
    )
    restrictions = RestrictionSerializer(source='*', required=False)


class TariffAltTextSerializer(SerializerCleanedUp):
    language = serializers.CharField(default='EN')
    text = serializers.CharField(source='price')


class MinPriceSerializer(SerializerCleanedUp):
    excl_vat = serializers.FloatField(source='min_price_excl_vat', default=None)
    incl_vat = serializers.FloatField(source='min_price_incl_vat', default=None)


class MaxPriceSerializer(SerializerCleanedUp):
    excl_vat = serializers.FloatField(source='max_price_excl_vat', default=None)
    incl_vat = serializers.FloatField(source='max_price_incl_vat', default=None)


class TariffSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Tariff
        exclude = ['updated', 'created', 'uid', 'archived', 'ocpi_master']

    id = serializers.CharField(source='uid', required=False,
                               help_text='Preferably a human readable, unique identifier')
    country_code = serializers.CharField(source='ocpi_master.country_code')
    party_id = serializers.CharField(source='ocpi_master.party_id')

    elements = ElementsSerializer(
        source='tariff_elements', many=True, required=True,
        help_text=f'See {settings.OCPI_SPECIFICATION_URL}mod_tariffs.asciidoc'
                  f'#mod_tariffs_tariffelement_class'
    )
    min_price = MinPriceSerializer(source='*', required=False,
                                   default=dict(min_price_excl_vat=None, min_price_incl_vat=None))
    max_price = MaxPriceSerializer(source='*', required=False,
                                   default=dict(max_price_excl_vat=None, max_price_incl_vat=None))

    tariff_alt_text = TariffAltTextSerializer(source='*', read_only=True)
    last_updated = UTCDateTimeField(required=False)

    def _delete_children(self, tariff: Tariff) -> None:
        """
        Remove TariffElements and PriceComponents from object - cascade delete should be enabled in Tariff child models
        """

        # noinspection PyUnresolvedReferences
        for te in tariff.tariff_elements.all():
            te.delete()

    def _create_children(self, tariff: Tariff, tariff_elements: dict) -> None:
        for te in tariff_elements:
            price_components = te.pop('price_components')
            tariff_element = TariffElement.objects.create(**te, tariff=tariff)
            for pc in price_components:
                PriceComponent.objects.create(**pc, tariff_element=tariff_element)

    def update(self, instance: Tariff, validated_data: dict) -> Tariff:
        tariff_elements = validated_data.pop('tariff_elements')
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        self._delete_children(instance)
        self._create_children(instance, tariff_elements)
        return instance

    def create(self, validated_data: dict) -> Tariff:
        tariff_elements = validated_data.pop('tariff_elements')
        tariff = Tariff.objects.create(**validated_data)
        self._create_children(tariff, tariff_elements)
        return tariff


class CdrCoordinatesSerializer(SerializerCleanedUp):
    latitude = Coordinate(source='cdr_location_latitude')
    longitude = Coordinate(source='cdr_location_longitude')


class CdrLocationSerializer(SerializerCleanedUp):
    id = serializers.CharField(source='cdr_location_id')
    address = serializers.CharField(source='cdr_location_address')
    name = serializers.CharField(source='cdr_location_name', required=False)
    city = serializers.CharField(source='cdr_location_city')
    postal_code = serializers.CharField(source='cdr_location_postal_code')
    country = serializers.CharField(source='cdr_location_country')
    coordinates = CdrCoordinatesSerializer(source='*')
    evse_uid = serializers.CharField(source='cdr_location_evse_uid')
    evse_id = serializers.CharField(source='cdr_location_evse_id')
    connector_id = serializers.CharField(source='cdr_location_connector_id')
    connector_standard = serializers.CharField(source='cdr_location_connector_standard')
    connector_format = serializers.CharField(source='cdr_location_connector_format')
    connector_power_type = serializers.CharField(source='cdr_location_connector_power_type')


class CdrSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Cdr
        fields = ['detail_url', 'country_code', 'party_id', 'id', 'start_date_time', 'end_date_time',
                  'session_id', 'cdr_token', 'auth_method', 'authorization_reference',
                  'cdr_location', 'tariffs', 'total_cost', 'total_energy', 'currency',
                  'total_time', 'credit', 'credit_reference_id', 'last_updated']

    id = serializers.CharField(source='uid')
    country_code = serializers.CharField(source='ocpi_master.country_code')
    party_id = serializers.CharField(source='ocpi_master.party_id')

    cdr_token = CdrTokenSerializer(source='*')
    total_cost = TotalCostSerializer(source='*')
    tariffs = TariffSerializer(many=True, required=True)
    cdr_location = CdrLocationSerializer(source='*')
    last_updated = UTCDateTimeField(required=False)
    start_date_time = UTCDateTimeField(required=True)
    end_date_time = UTCDateTimeField(required=True)

    def create(self, validated_data):
        try:
            tariffs = validated_data.pop('tariffs')
            tariff_serializer = TariffSerializer()
            tariff_list = []
            for tariff in tariffs:
                # Create archived copies of the relevant Tariffs, so that they don't change anymore
                tariff['archived'] = True
                # Todo: Store CDRs as json in the database
                tariff['ocpi_master'] = get_credentialsrole(None, Party(**tariff.pop('ocpi_master')),
                                                            role=OcpiRolesEnum.CPO)
                tariff_list.append(tariff_serializer.create(tariff))
            cdr = Cdr.objects.create(**validated_data)
            cdr.tariffs.set(tariff_list)
            return cdr
        except IntegrityError:
            raise serializers.ValidationError('The CDR with this UID already exists. '
                                  'Overwriting an existing CDR is not possible.', code='invalid')


class RolesSerializer(serializers.ModelSerializer):
    class Meta:
        model = CredentialsRole
        # Todo: Should there be country_code and party_id here?
        fields = ('ocpi_master', 'role', 'business_details')

    business_details = BusinessDetailsSerializer()


class CredentialsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Credentials
        fields = ('token', 'url', 'roles')

    token = serializers.CharField(source='theirs')
    url = serializers.URLField()
    roles = RolesSerializer(many=True)

    def create(self, validated_data):
        credentials = Credentials.objects.create(
            theirs=base64_to_ascii(validated_data.get('token')),
            url=validated_data.get('url')
        )

        credentials.roles.all().delete()

        for role in validated_data['roles']:
            credentials.add_role(role)

        # Delay storing tokens until now, in case the roles have some issue
        credentials.save()

    def update(self, instance, validated_data):
        instance.theirs = validated_data.get('theirs')
        instance.url = validated_data.get('url')

        # DO NOT allow changing the roles of an existing Credentials object, or other parties can pretend to be anyone

        # Delay storing tokens until now, in case the roles have some issue
        instance.save()
        return instance


class LocationIdDictSerializer(serializers.CharField):
    # location_id = serializers.CharField(required=True)
    default_error_messages = default_error_messages

    def __init__(self, *args, **kwargs):
        super().__init__(max_length=settings.OCPI_22_MAX_UID_LENGTH, **kwargs)

    def to_representation(self, instance: Union[Session, Location]):
        if isinstance(instance, str):
            return instance
        if isinstance(instance, Session):
            return instance.location.uid
        if isinstance(instance, dict):
            instance = instance.get('location')
        if instance:
            return instance.uid

    def to_internal_value(self, data: str):
        location = Location.get_if_exists(uid=data)
        if not location:
            self.fail('object_missing', name='Location', uid=data)
        return dict(location=location)


class LocationEvseUidSerializer(serializers.Serializer):
    default_error_messages = default_error_messages

    def get_location_id(self):
        if hasattr(self.parent, 'parent') and self.parent.parent:
            return self.parent.parent.initial_data.get('location_id')
        elif hasattr(self, 'parent') and self.parent:
            return self.parent.initial_data.get('location_id')
        return None

    def to_internal_value(self, evse_uid):
        location_id = self.get_location_id()
        evse = Evse.get_if_exists(uid=evse_uid, location__uid=location_id)
        if not evse:
            self.fail('location_evse_missing', evse=evse_uid, location=location_id)
        return evse


class EvseUidDictSerializer(LocationEvseUidSerializer):
    evse_uid = serializers.CharField(required=True)
    default_error_messages = default_error_messages

    def to_representation(self, instance: Session):
        return instance.evse.uid

    def to_internal_value(self, data: str):
        evse = super().to_internal_value(data)
        return dict(evse=evse)


class ConnectorIdSerializer(serializers.Serializer):
    default_error_messages = default_error_messages

    def to_representation(self, instance: Session):
        return instance.connector.uid if hasattr(instance, 'connector') and instance.connector else None

    def to_internal_value(self, connector_id: str):
        evse_uid = self.parent.initial_data.get('evse_uid') or self.parent.initial_data.get('evse')
        location_id = self.parent.initial_data.get('location_id') or self.parent.initial_data.get('location')
        evse = Evse.get_if_exists(uid=evse_uid, location__uid=location_id)
        connector = Connector.get_if_exists(uid=connector_id, evse=evse)
        if not connector:
            self.fail('object_missing', name='Connector', uid=connector_id)
        return dict(connector=connector)


def update_charging_periods(session, chargingperiods):
    for chargingperiod in chargingperiods:
        dimensions = chargingperiod.pop('dimensions', None)
        if not dimensions:
            raise ValidationError(f'Chargingperiod {chargingperiod.get("start_date_time", None)} '
                                  f'is missing CdrDimensions')

        # Do we need to update an existing one?
        start_date_time = chargingperiod.get('start_date_time')
        cp = ChargingPeriod.get_if_exists(start_date_time=start_date_time)
        if cp:
            # Let's rewrite the incoming dimensions
            cp.dimensions.all().delete()
        else:
            cp = ChargingPeriod.objects.create(**chargingperiod, session=session)

        for dimension in dimensions:
            CdrDimension.objects.create(**dimension, chargingperiod=cp)


class SessionSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Session
        fields = ['detail_url', 'country_code', 'party_id', 'id',
                  'start_date_time', 'end_date_time',
                  'kwh', 'charging_periods',
                  'cdr_token', 'auth_method', 'authorization_reference',
                  'location_id', 'evse_uid', 'connector_id', 'meter_id', 'currency', 'total_cost',
                  'status', 'last_updated']

    id = serializers.CharField(source='uid', max_length=settings.OCPI_22_MAX_UID_LENGTH)
    country_code = CiStringField(source='ocpi_master.country_code')
    party_id = CiStringField(source='ocpi_master.party_id')

    charging_periods = ChargingPeriodSerializer(many=True, source='chargingperiods', required=False)
    cdr_token = CdrTokenSerializer(required=True, source='*')
    location_id = LocationIdDictSerializer(source='*')
    evse_uid = EvseUidDictSerializer(source='*')
    connector_id = ConnectorIdSerializer(source='*', required=False)
    total_cost = TotalCostSerializer(source='*', required=False)

    start_date_time = UTCDateTimeField(format=settings.OCPI_DATE_FORMAT)
    end_date_time = UTCDateTimeField(required=False)

    last_updated = UTCDateTimeField(required=False)
    kwh = serializers.FloatField(required=False)

    def create(self, validated_data):
        request = self.context.get("request")
        chargingperiods = validated_data.pop('chargingperiods', [])
        session = Session.objects.create(
            credentials=request.credentials,
            billed_to=None,  # If we are CPO, we fill the billed_to elsewhere and MSP doesn't use it
            # ocpi_master=request.ocpi_party,
            **validated_data
        )
        for chargingperiod in chargingperiods:
            dimensions = chargingperiod.pop('dimensions', None)
            cp = ChargingPeriod.objects.create(**chargingperiod, session=session)
            for dimension in dimensions:
                CdrDimension.objects.create(**dimension, chargingperiod=cp)
        return session

    def update(self, instance, validated_data):
        # Todo: Any charging_periods from the existing object SHALL be replaced by the charging_periods
        #  from the newly received Session object. If the new Session object does not contain charging_periods
        #  (field is omitted or contains any empty list), the charging_periods of the existing object
        #  SHALL be removed (replaced by the new empty list).

        readonly_fields = ('uid', 'location', 'evse')
        for key in readonly_fields:
            validated_data.pop(key, None)
        chargingperiods = validated_data.pop('chargingperiods', None)
        if chargingperiods:
            update_charging_periods(instance, chargingperiods)

        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()

        return instance


class ClientInfoSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = CredentialsRole
        fields = ('country_code', 'party_id', 'role', 'status', 'last_updated')

    status = serializers.ChoiceField(
        choices=CONNECTION_STATUS_CHOICES, source='credentials.connection_status'
    )
    last_updated = UTCDateTimeField(
        source='credentials.last_connection', format=settings.OCPI_DATE_FORMAT
    )


class LocationIdSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        return Location.get_if_exists(uid=data) or data


class StrictLocationIdSerializer(serializers.CharField):
    def to_internal_value(self, data):
        result = Location.get_if_exists(uid=data)
        if not result:
            raise ValidationError(f"Location {data} cannot be found from MSP database")
        return result


class EvseUidSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        return Evse.get_if_exists(uid=data)


class StrictEvseUidSerializer(serializers.CharField):
    def to_internal_value(self, data):
        evse = None
        location_id = 'N/A'
        if hasattr(self, 'parent'):
            location_id = self.parent.initial_data.get('location_id')
            if not location_id and hasattr(self.parent, 'parent'):
                location_id = self.parent.parent.initial_data.get('location_id')
                if not location_id:
                    raise TypeError('Unable to read location_id')
            evse = Evse.get_if_exists(uid=data, location__uid=location_id)
        if not evse:
            raise ValidationError(f'Evse with UID {data} at location {location_id} is unknown')
        return evse


class AuthorizeSerializer(serializers.Serializer):
    location_id = StrictLocationIdSerializer(source='location', required=False)
    evse_uids = LocationEvseUidSerializer(source='evses', many=True, required=False)

# class MspAuthorizationResponseSerializer(serializers.Serializer):
#     result = serializers.ChoiceField(choices=AuthorizationEnum.choices)
