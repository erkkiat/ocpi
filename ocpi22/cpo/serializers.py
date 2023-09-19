from decimal import Decimal
from typing import Union

from django.conf import settings
from rest_framework import serializers, fields
from rest_framework.exceptions import ValidationError

from ocpi22.choices import OcppStatusChoices, TOKEN_TYPE_CHOICES
from ocpi22.commands.serializers import CommandResultBaseSerializer
from ocpi22.cpo.util import _find_our_evse
from ocpi22.models.location import Evse, Connector, Location
from ocpi22.models.session import Session
from ocpi22.models.tariff import Tariff, TariffElement, PriceComponent
from ocpi22.models.token import Token
from ocpi22.ocpi.serializers import CdrSerializer
from ocpi22.util import clear_empty, uid_validator, CURRENCY_CHOICES, fill_out_location_address
from ocpi22.serializers import SerializerCleanedUp, HyperlinkedModelSerializerCleanedUp, CallbacksSerializer


class EvseSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Evse
        fields = ['url', 'uid', 'status', 'last_updated']

    uid = serializers.CharField(read_only=True)
    last_updated = serializers.DateTimeField(format=settings.OCPI_DATE_FORMAT, required=False)


class CpoSessionSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Session
        fields = ['detail_url', 'session_id', 'internal_reference', 'billed_to',
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
    start_date_time = serializers.DateTimeField(format=settings.OCPI_DATE_FORMAT)
    end_date_time = serializers.DateTimeField(format=settings.OCPI_DATE_FORMAT, required=False)
    last_updated = serializers.DateTimeField(format=settings.OCPI_DATE_FORMAT, required=False)

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
    last_updated = serializers.DateTimeField(format=settings.OCPI_DATE_FORMAT, required=False)


class EvseQuickSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Evse
        fields = ['status_url', 'uid', 'connectors', 'last_updated']

    uid = serializers.CharField(validators=[uid_validator], max_length=settings.OCPI_22_MAX_UID_LENGTH)
    connectors = ConnectorQuickSerializer(many=True)


class LocationQuickSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Location
        fields = [
            'quick_url', 'id',
            'name', 'language', 'address', 'city', 'postal_code', 'state', 'country', 'time_zone',
            'latitude', 'longitude', 'evses'
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
    latitude = serializers.FloatField(required=False)
    longitude = serializers.FloatField(required=False)
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
        Location.objects.filter(uid__iexact=location.uid).update(**validated_data)
        for evse_dict in evses:
            connectors = evse_dict.pop('connectors', [])
            evse, created = Evse.objects.get_or_create(location=location, uid__iexact=evse_dict.get('uid'),
                                                       defaults=evse_dict)
            if not created:
                Evse.objects.filter(uid__iexact=evse.uid).update(**evse_dict)
            for connector_dict in connectors:
                tariff_ids = connector_dict.pop('tariff_ids', None)
                connector, created = Connector.objects.get_or_create(evse=evse,
                                                                     uid=connector_dict.pop('uid'),
                                                                     defaults=connector_dict)
                if not created:
                    Connector.objects.filter(uid__iexact=connector.uid, evse=evse).update(**connector_dict)
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
    The session start and end time are recorded by the system
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
    timestamp = serializers.DateTimeField(
        required=False,
        help_text="Optional timestamp for the meter values. Using this field is highly recommended, so that "
                  "disruptions in connectivity won't distort cost calculation."
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

    def is_adhoc_token(self) -> bool:
        return isinstance(self.validated_data.get('token'), str)


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
    stop_timestamp = serializers.DateTimeField(
        required=False,
        help_text='The timestamp of the moment when the driver has unplugged the vehicle'
    )

    def validate(self, attrs):
        if 'session' not in attrs and 'internal_reference' not in attrs:
            raise ValidationError('Please specify either the session_id or the internal_reference')
        return attrs


# class CPOCallbacksSerializer(CallbacksSerializer):
#     """
#     The URLs for callback endpoints in the CPO system
#     """
#     START_TRANSACTION_URL = 'start_transaction_url'
#     STOP_TRANSACTION_URL = 'stop_transaction_url'
#
#     start_transaction_url = serializers.URLField()
#     stop_transaction_url = serializers.URLField()
#
#     # unlock_connector_url = serializers.URLField(required=False)
#     # reserve_now_url = serializers.URLField(required=False)
#     # cancel_reservation_url = serializers.URLField(required=False)

# class CPOCallbacksSerializer(CallbacksSerializer):
#     """
#     The URLs for callback endpoints in the CPO system
#     """
#     START_TRANSACTION_URL = 'start_transaction_url'
#     STOP_TRANSACTION_URL = 'stop_transaction_url'
#
#     start_transaction_url = serializers.URLField()
#     stop_transaction_url = serializers.URLField()
#
#     # unlock_connector_url = serializers.URLField(required=False)
#     # reserve_now_url = serializers.URLField(required=False)
#     # cancel_reservation_url = serializers.URLField(required=False)


class CpoOutboundWebhookSerializer(serializers.Serializer):
    response_url = serializers.URLField()
    token_id = serializers.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH)
    token_type = serializers.ChoiceField(choices=TOKEN_TYPE_CHOICES)
    authorization_reference = serializers.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH, required=False,
                                                    allow_null=True)
    auth_method = serializers.ChoiceField(choices=Session.AUTH_METHOD_CHOICES)
    from_party = serializers.CharField()
    evse_id = serializers.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH, required=False, allow_null=True)
    connector_id = serializers.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH, required=False, allow_null=True)
    billed_to = serializers.CharField(max_length=6)


class CPOStartWebhookSerializer(CallbacksSerializer):
    URL = 'start_transaction_url'
    start_transaction_url = serializers.URLField()

    class OutboundSerializer(CpoOutboundWebhookSerializer):
        token_type = serializers.ChoiceField(choices=TOKEN_TYPE_CHOICES)
        connector_id = serializers.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH, required=False,
                                             allow_null=True)

    class ResponseSerializer(serializers.Serializer):
        timeout = serializers.IntegerField(required=False, allow_null=True)
        result = serializers.ChoiceField(choices=CommandResultBaseSerializer.RESULT_OPTIONS)


class CPOStopWebhookSerializer(CallbacksSerializer):
    URL = 'stop_transaction_url'
    stop_transaction_url = serializers.URLField()

    class OutboundSerializer(CpoOutboundWebhookSerializer):
        token_type = serializers.ChoiceField(choices=TOKEN_TYPE_CHOICES)
        connector_id = serializers.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH, required=False,
                                             allow_null=True)

    class ResponseSerializer(serializers.Serializer):
        timeout = serializers.IntegerField(required=False, allow_null=True)
        result = serializers.ChoiceField(choices=CommandResultBaseSerializer.RESULT_OPTIONS)


class CPOReserveNowWebhookSerializer(CallbacksSerializer):
    URL = 'reserve_now_url'
    reserve_now_url = serializers.URLField()

    class OutboundSerializer(CpoOutboundWebhookSerializer):
        expiry_date = serializers.DateTimeField()
        location_id = serializers.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH)
        reservation_id = serializers.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH)

    class ResponseSerializer(serializers.Serializer):
        timeout = serializers.IntegerField(required=False, allow_null=True)
        result = serializers.ChoiceField(choices=CommandResultBaseSerializer.RESULT_OPTIONS)


class VatSerializer(serializers.IntegerField):
    key = 'vat'

    def to_representation(self, tariff: Tariff) -> Union[int, str]:
        pe = tariff.tariff_elements.first()
        # Iterate through the VATs for this Tariff and check if there are multiple different ones
        vats = set(pe.price_components.values_list('vat', flat=True))
        if len(vats) == 1:
            return vats.pop()
        return 'Multiple'

    def to_internal_value(self, data) -> dict:
        return {self.key: self.validate(data)}

    def validate(self, data):
        if data:
            if not (0 <= data <= 100):
                raise ValidationError(f'VAT percentage can only be between 0 and 100')
            if 0 < data < 1:
                raise ValidationError(f'VAT needs to be an integer value between 0 and 100')
        return data


class PriceSerializer(serializers.DecimalField):
    def to_representation(self, tariff: Tariff) -> Decimal:
        pc = tariff.get_type(self.tariff_type)
        return pc.price if pc else None

    def to_internal_value(self, data):
        result = {self.key: data}
        return result


class PriceKwhSerializer(PriceSerializer):
    tariff_type = 'ENERGY'
    key = 'price_per_kwh'


class PriceMinSerializer(PriceSerializer):
    tariff_type = 'TIME'
    key = 'price_per_min'


class PriceFlatSerializer(PriceSerializer):
    tariff_type = 'FLAT'
    key = 'price_flat'


class TariffQuickSerializer(SerializerCleanedUp):
    id = serializers.CharField(source='uid', validators=[uid_validator], max_length=settings.OCPI_22_MAX_UID_LENGTH)
    currency = serializers.ChoiceField(choices=CURRENCY_CHOICES, default='EUR')
    price_per_kwh = PriceKwhSerializer(
        source='*',
        max_digits=8, decimal_places=4, required=False,
        help_text='The price per kWh of electricity charged excluding tax'
    )
    price_per_min = PriceMinSerializer(
        source='*',
        max_digits=8, decimal_places=4, required=False,
        help_text='The price per minute of charging, excluding parking and tax'
    )
    price_flat = PriceFlatSerializer(
        source='*',
        max_digits=8, decimal_places=4, required=False,
        help_text='The flat price per started charging session excluding tax'
    )
    vat = VatSerializer(
        source='*',
        required=False, allow_null=True,
        help_text='The Value Added Tax amount in percentage'
    )

    def create(self, validated_data):
        tariff = Tariff.objects.create(uid=validated_data.get('uid'), ocpi_master=validated_data.get('ocpi_master'))
        te = TariffElement.objects.create(tariff=tariff)
        per_kwh = validated_data.get(PriceKwhSerializer.key)
        per_min = validated_data.get(PriceMinSerializer.key)
        flat = validated_data.get(PriceFlatSerializer.key)
        vat = validated_data.get(VatSerializer.key)

        if per_kwh:
            PriceComponent.objects.create(tariff_element=te, type='ENERGY', price=per_kwh, vat=vat, step_size=1)
        if per_min:
            PriceComponent.objects.create(tariff_element=te, type='TIME', price=per_min, vat=vat, step_size=1)
        if flat:
            PriceComponent.objects.create(tariff_element=te, type='FLAT', price=flat, vat=vat, step_size=1)
        return tariff

    def update(self, tariff: Tariff, validated_data: dict):
        def update_price_components(price, tariff_type) -> None:
            data = dict(price=price, vat=vat, step_size=1)
            pc, created = PriceComponent.objects.get_or_create(tariff_element=te, type=tariff_type, defaults=data)
            if not created:
                for key, value in data.items():
                    if value is not None:
                        setattr(pc, key, value)
                pc.save()

        te, _created = TariffElement.objects.get_or_create(tariff=tariff)
        per_kwh = validated_data.get(PriceKwhSerializer.key)
        per_min = validated_data.get(PriceMinSerializer.key)
        flat = validated_data.get(PriceFlatSerializer.key)
        vat = validated_data.get(VatSerializer.key)

        price_components = (
            (per_kwh, 'ENERGY'),
            (per_min, 'TIME'),
            (flat, 'FLAT'),
        )
        for price, tariff_type in price_components:
            if price is not None:
                update_price_components(price, tariff_type)

        if vat is not None:
            te.price_components.update(vat=vat)

        return tariff


class InvoicingCallbackSerializer(CallbacksSerializer):
    URL = 'invoicing_url'  # Must match with below
    invoicing_url = serializers.URLField()

    class OutboundSerializer(CdrSerializer):
        pass

    class ResponseSerializer(serializers.Serializer):
        pass
