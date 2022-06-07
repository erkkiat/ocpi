import uuid

from icecream import ic
from rest_framework import serializers, fields
from rest_framework.exceptions import ValidationError

from ocpi22.choices import OCPP_STATUS_CHOICES, OcppStatusEnum
from ocpi22.cpo.util import _find_our_evse, set_callbacks_parameter
from ocpi22.models.location import Evse, Connector, Location
from ocpi22.models.session import Session
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
                  'start_date_time', 'end_date_time', 'start_kwh',
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


class ConnectorQuickSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Connector
        fields = ['uid', 'standard', 'format',
                  'max_voltage', 'max_amperage', 'max_electric_power',
                  'tariff_ids', 'last_updated']

    uid = serializers.CharField(validators=[uid_validator])
    max_electric_power = serializers.SerializerMethodField()
    tariff_ids = serializers.SerializerMethodField()
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)

    @staticmethod
    def get_tariff_ids(connector: Connector) -> list:
        return [t.uid for t in connector.tariff_ids.all()]

    @staticmethod
    def get_max_electric_power(connector: Connector) -> str:
        # Todo: what about 1-phase and 2-phase AC?
        return connector.max_electric_power or connector.max_voltage * connector.max_amperage


class EvseQuickSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Evse
        fields = ['status_url', 'uid', 'status', 'connectors', 'last_updated']

    uid = serializers.CharField(validators=[uid_validator])
    connectors = ConnectorQuickSerializer(many=True)


class LocationQuickSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Location
        fields = [
            'quick_url', 'id',
            'name', 'address', 'city', 'postal_code', 'state', 'country',
            'latitude', 'longitude', 'evses',
        ]

    id = serializers.CharField(source='uid', validators=[uid_validator])
    evses = EvseQuickSerializer(many=True)

    lookup_field = 'uid'

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
        evses = validated_data.pop('evses', [])
        Location.objects.filter(uid=location.uid).update(**validated_data)
        for evse_dict in evses:
            connectors = evse_dict.pop('connectors', [])
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
        super().__init__(OCPP_STATUS_CHOICES)

    def to_internal_value(self, data):
        result = {
            OcppStatusEnum.AVAILABLE.value: 'AVAILABLE',
            OcppStatusEnum.PREPARING.value: 'CHARGING',
            OcppStatusEnum.CHARGING.value: 'CHARGING',
            OcppStatusEnum.SUSPENDEDEV.value: 'CHARGING',
            OcppStatusEnum.SUSPENDEDEVSE.value: 'CHARGING',
            OcppStatusEnum.FINISHING.value: 'CHARGING',
            OcppStatusEnum.RESERVED.value: 'RESERVED',
            OcppStatusEnum.UNAVAILABLE.value: 'CHARGING',
            OcppStatusEnum.FAULTED.value: 'OUTOFORDER',
        }.get(data.upper())
        if not result:
            options = [x[0] for x in OCPP_STATUS_CHOICES]
            raise ValidationError(f"'{data}' is not a known OCPP status. Options are: {options}.")
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
        max_length=36,
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
