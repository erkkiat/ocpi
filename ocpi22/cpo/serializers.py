from typing import Union

import pycountry
from django.conf import settings
from geopy import Nominatim
from rest_framework import serializers, fields
from rest_framework.exceptions import ValidationError
from timezonefinder import TimezoneFinder

from ocpi22.choices import OcppStatusChoices
from ocpi22.cpo.util import _find_our_evse, set_callbacks_parameter
from ocpi22.models.location import Evse, Connector, Location
from ocpi22.models.session import Session
from ocpi22.models.tariff import Tariff
from ocpi22.models.token import Token
from ocpi22.util import HyperlinkedModelSerializerCleanedUp, clear_empty, uid_validator


class EvseSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Evse
        fields = ['url', 'uid', 'status', 'last_updated']

    uid = serializers.CharField(read_only=True)
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)


class CpoSessionSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Session
        fields = ['session_id', 'internal_reference', 'billed_to',
                  'start_date_time', 'end_date_time', 'start_kwh', 'stop_kwh',
                  'token', 'auth_method', 'authorization_reference',
                  'location_id', 'evse_uid', 'connector_id', 'currency',
                  'total_cost_incl_vat', 'total_cost_excl_vat',
                  'status', 'last_updated']

    session_id = serializers.CharField(source='uid', read_only=True)
    internal_reference = serializers.CharField(read_only=True)
    token = serializers.SerializerMethodField(read_only=True)
    location_id = serializers.SerializerMethodField(read_only=True)
    evse_uid = serializers.SerializerMethodField(read_only=True)
    connector_id = serializers.SerializerMethodField(read_only=True)
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)

    @staticmethod
    def get_token(session):
        return clear_empty(dict(
            token_id=session.cdr_token_uid,
            type=session.cdr_token_type,
            contract_id=session.cdr_token_contract_id
        ))

    @staticmethod
    def get_location_id(session):
        return session.location.uid

    @staticmethod
    def get_evse_uid(session):
        return session.evse.uid

    @staticmethod
    def get_connector_id(session):
        return session.connector.uid \
            if session and hasattr(session, 'connector') and session.connector else ''


class ConnectorTariffIdSerializer(serializers.Serializer):
    def to_representation(self, instance):
        return instance.uid

    def to_internal_value(self, data):
        tariff = Tariff.objects.filter(uid=data).first()
        if not tariff:
            raise ValidationError(f'Tariff {data} is not in the database, please create it before adding Locations')
        return tariff


class ConnectorQuickSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Connector
        fields = ['uid', 'standard', 'format',
                  'max_voltage', 'max_amperage', 'max_electric_power',
                  'tariff_ids', 'last_updated']

    uid = serializers.CharField(validators=[uid_validator], max_length=settings.OCPI_22_MAX_UID_LENGTH)
    tariff_ids = ConnectorTariffIdSerializer(required=False, many=True)
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)


class EvseQuickSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Evse
        fields = ['status_url', 'uid', 'connectors', 'last_updated']

    uid = serializers.CharField(validators=[uid_validator], max_length=settings.OCPI_22_MAX_UID_LENGTH)
    connectors = ConnectorQuickSerializer(many=True)


def country_code_from_2_to_3_chars(country_code: str) -> str:
    country = pycountry.countries.get(alpha_2=country_code)
    return country.alpha_3


def fill_out_location_address(data: dict, lat: Union[float, str], lng: Union[float, str]) -> dict:
    language = data.pop('language', False)
    if 'address' in data and 'city' in data and 'country' in data:
        return data
    if not lat or not lng:
        return data
    locator = Nominatim(user_agent="ChargerHub.EU")
    coordinates = f"{lat},{lng}"
    location = locator.reverse(coordinates, language=language)
    address = location.raw.get('address')
    data['address'] = f"{address.get('road') or '-'} {address.get('house_number')}"
    data['city'] = address.get('city') or '-'
    data['postal_code'] = address.get('postcode') or '-'
    data['country'] = country_code_from_2_to_3_chars(address.get('country_code'))

    # Fill out the time zone based on coordinates
    tf = TimezoneFinder()
    data['time_zone'] = tf.timezone_at_land(lat=lat, lng=lng)

    return data


class LocationQuickSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Location
        fields = [
            'quick_url', 'id',
            'name', 'language', 'address', 'city', 'postal_code', 'state', 'country', 'time_zone',
            'latitude', 'longitude', 'evses',
        ]

    id = serializers.CharField(source='uid', validators=[uid_validator], max_length=settings.OCPI_22_MAX_UID_LENGTH)
    evses = EvseQuickSerializer(many=True, required=False)
    language = serializers.CharField(
        required=False, max_length=6,
        help_text='Optional language of the location address, if address is determined based on coordinates'
    )
    address = serializers.CharField(
        required=False, max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH,
        help_text='If omitted, street address will be determined automatically based on coordinates'
    )
    city = serializers.CharField(
        required=False, max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH,
        help_text='If omitted, city will be determined automatically based on coordinates'
    )
    country = serializers.CharField(
        required=False, max_length=3,
        help_text='If omitted, country will be determined automatically based on coordinates'
    )
    time_zone = serializers.CharField(
        required=False, max_length=settings.OCPI_22_MAX_TIME_ZONE_LENGTH,
        help_text='If omitted, time zone will be determined automatically based on coordinates'
    )
    lookup_field = 'uid'

    def create(self, validated_data, *args, **kwargs):
        evses = validated_data.pop('evses', [])
        validated_data = fill_out_location_address(
            validated_data,
            validated_data.get('latitude'),
            validated_data.get('longitude')
        )
        location = Location.objects.create(**validated_data)
        for evse_dict in evses:
            connectors = evse_dict.pop('connectors', [])
            evse = Evse.objects.create(location=location, **evse_dict)
            for connector_dict in connectors:
                tariff_ids = connector_dict.pop('tariff_ids', None)
                connector = Connector.objects.create(evse=evse, **connector_dict)
                if tariff_ids:
                    connector.tariff_ids.set(tariff_ids)
                else:
                    connector.tariff_ids.clear()
        return location

    def update(self, location, validated_data, *args, **kwargs):
        evses = validated_data.pop('evses', [])
        validated_data = fill_out_location_address(
            validated_data,
            validated_data.get('latitude'),
            validated_data.get('longitude')
        )
        Location.objects.filter(uid=location.uid).update(**validated_data)
        for evse_dict in evses:
            connectors = evse_dict.pop('connectors', [])
            evse, created = Evse.objects.get_or_create(location=location, uid=evse_dict.pop('uid'),
                                                       defaults=evse_dict)
            if not created:
                Evse.objects.filter(uid=evse.uid).update(**evse_dict)
            for connector_dict in connectors:
                tariff_ids = connector_dict.pop('tariff_ids', None)
                connector, created = Connector.objects.get_or_create(evse=evse,
                                                                     uid=connector_dict.pop('uid'),
                                                                     defaults=connector_dict)
                if not created:
                    Connector.objects.filter(uid=connector.uid, evse=evse).update(**connector_dict)
                if tariff_ids:
                    connector.tariff_ids.set(tariff_ids)
        return location


class EvseSerialnumberSerializer(fields.CharField):
    def to_internal_value(self, evse_uid):
        return _find_our_evse(evse_uid)


class TokenIdSerializer(fields.CharField):
    # Find a token with token_id or keep the token_id (for AD HOC tokens)
    def to_internal_value(self, data):
        token = Token.get_if_exists(uid=data) or data
        return token


class SessionIdSerializer(fields.CharField):
    def to_internal_value(self, data):
        if data:
            return Session.objects.get(uid=data)
        return None


class OcppStatusSerializer(fields.ChoiceField):
    def __init__(self):
        super().__init__(OcppStatusChoices.choices)

    def to_internal_value(self, data):
        result = {
            OcppStatusChoices.AVAILABLE: 'AVAILABLE',
            OcppStatusChoices.PREPARING: 'CHARGING',
            OcppStatusChoices.CHARGING: 'CHARGING',
            OcppStatusChoices.SUSPENDEDEV: 'CHARGING',
            OcppStatusChoices.SUSPENDEDEVSE: 'CHARGING',
            OcppStatusChoices.FINISHING: 'CHARGING',
            OcppStatusChoices.RESERVED: 'RESERVED',
            OcppStatusChoices.UNAVAILABLE: 'CHARGING',
            OcppStatusChoices.FAULTED: 'OUTOFORDER',
        }.get(data.upper())
        if not result:
            raise ValidationError(f"'{data}' is not a known OCPP status. Options are: {OcppStatusChoices.values}.")
        return result


class StatusChangeSerializer(serializers.Serializer):
    evse_id = EvseSerialnumberSerializer(
        source='evse',
        help_text='The identifier of the device which provides electricity to one or more connectors'
    )
    status = OcppStatusSerializer()


class AuthorizationSerializer(serializers.Serializer):
    evse_id = EvseSerialnumberSerializer(
        source='evse',
        help_text='The identifier of the device which provides electricity to one or more connectors'
    )
    token_id = TokenIdSerializer(
        source='token',
        help_text='The hidden ID of the RFID token, separate from the visual one'
    )


class MeterValuesSerializer(serializers.Serializer):
    """
    The session start and end time are recorded by the OCPI Connector
    """
    session_id = SessionIdSerializer(
        source='session', required=False,
        help_text='The optional OCPI session ID (from the response of the start_transaction endpoint)',
    )
    internal_reference = serializers.CharField(
        required=False,
        help_text='The optional internal reference on the CPO platform '
                  '(for example order number from the billing system)',
    )
    kwh = serializers.FloatField(
        help_text='The kWh measurement at the time of this message',
    )
    soc = serializers.FloatField(
        required=False, min_value=0, max_value=100,
        help_text='The optional State of Charge for the vehicle, if provided by the charge point',
    )
    power = serializers.FloatField(
        required=False,
        help_text='Optional total amount of energy (dis-)charged during this ChargingPeriod: defined in kWh. '
                  'When negative, more energy was feed into the grid then charged into the EV. '
                  'Default step_size is 1.',
    )

    def validate(self, attrs):
        if 'session' not in attrs and 'internal_reference' not in attrs:
            raise ValidationError('Please specify either the session_id or the internal_reference')
        return attrs


class StartTransactionSerializer(serializers.Serializer):
    evse_id = EvseSerialnumberSerializer(
        source='evse',
        help_text='The identifier of the device which provides electricity to one or more connectors'
    )
    connector_id = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        help_text='The connector number used for charging during this transaction'
    )
    token_id = TokenIdSerializer(
        source='token',
        help_text='The hidden ID of the RFID token, separate from the visual one'
    )
    internal_reference = serializers.CharField(
        max_length=36,
        help_text='The session ID on the CPO platform or order number from the CPO billing system',
        required=False, allow_null=True
    )
    start_kwh = serializers.FloatField(
        required=False,
        default=0.0,
        help_text='The optional kWh measurement at the meter at start of the transaction, can start from zero '
                  'or start from where the previous charging session ended or some other value'
    )


class StopTransactionSerializer(serializers.Serializer):
    """
    The session ends with a specific meter value
    """
    session_id = SessionIdSerializer(
        source='session', required=False,
        help_text='The optional OCPI session ID (from the response of the start_transaction endpoint)',
    )
    internal_reference = serializers.CharField(
        required=False,
        help_text='The optional internal reference on the CPO platform '
                  '(for example order number from the billing system)',
    )
    stop_kwh = serializers.DecimalField(
        max_digits=8, decimal_places=4, required=False,
        help_text='Optionally, the final kWh reading from the charger',
    )

    def validate(self, attrs):
        if 'session' not in attrs and 'internal_reference' not in attrs:
            raise ValidationError('Please specify either the session_id or the internal_reference')
        return attrs


class CallbacksSerializer(serializers.Serializer):
    """
    The URLs for callback endpoints in the CPO system
    """
    START_TRANSACTION_URL = 'start_transaction_url'
    STOP_TRANSACTION_URL = 'stop_transaction_url'

    start_transaction_url = serializers.URLField()
    stop_transaction_url = serializers.URLField()

    # unlock_connector_url = serializers.URLField(required=False)
    # reserve_now_url = serializers.URLField(required=False)
    # cancel_reservation_url = serializers.URLField(required=False)

    def save(self):
        for key, value in self.validated_data.items():
            set_callbacks_parameter(key, value)
        # redis_store.save()  # This is not allowed in Heroku Redis
