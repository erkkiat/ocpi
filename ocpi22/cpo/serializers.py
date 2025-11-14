import logging
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from rest_framework import serializers, fields
from rest_framework.exceptions import ValidationError

from ocpi22.choices import (
    OcppStatusChoices,
    TOKEN_TYPE_CHOICES,
    AuthorizationEnum,
)
from ocpi22.commands.serializers import CommandResultBaseSerializer
from ocpi22.cpo.services import SolidTariffService
from ocpi22.cpo.util import find_our_evse
from ocpi22.models import enum
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.location import Evse
from ocpi22.models.session import Session
from ocpi22.models.tariff import Tariff, SolidTariff
from ocpi22.models.token import Token
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.serializers.util import (
    SerializerCleanedUp,
    HyperlinkedModelSerializerCleanedUp,
    CallbacksSerializer,
    UTCDateTimeField,
)
from ocpi22.util import (
    clear_empty,
    uid_validator,
    CURRENCY_CHOICES,
    get_currency_choices,
)

from ocpiconnector.party import Party

logger = logging.getLogger(__name__)


class EvseSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Evse
        fields = ["url", "uid", "status", "last_updated"]

    uid = serializers.CharField(read_only=True)
    last_updated = UTCDateTimeField(required=False)


class CpoSessionSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Session
        fields = [
            "detail_url",
            "session_id",
            "billed_to",
            "start_date_time",
            "end_date_time",
            "start_kwh",
            "stop_kwh",
            "token",
            "auth_method",
            "authorization_reference",
            "location_id",
            "evse_uid",
            "connector_id",
            "currency",
            "total_cost_incl_vat",
            "total_cost_excl_vat",
            "total_kwh",
            "status",
            "last_updated",
        ]

    session_id = serializers.CharField(source="uid", read_only=True)
    token = serializers.SerializerMethodField(read_only=True)
    billed_to = serializers.SerializerMethodField(read_only=True)
    location_id = serializers.SerializerMethodField(read_only=True)
    evse_uid = serializers.SerializerMethodField(read_only=True)
    connector_id = serializers.SerializerMethodField(read_only=True)
    start_date_time = UTCDateTimeField(format=settings.OCPI_DATE_FORMAT)
    end_date_time = UTCDateTimeField(required=False)
    last_updated = UTCDateTimeField(required=False)
    total_kwh = serializers.SerializerMethodField(read_only=True)

    @staticmethod
    def get_total_kwh(session):
        return session.stop_kwh - session.start_kwh

    @staticmethod
    def get_token(session):
        return clear_empty(
            dict(
                country_code=session.cdr_token.ocpi_master.country_code,
                party_id=session.cdr_token.ocpi_master.party_id,
                token_id=session.cdr_token.uid,
                type=session.cdr_token.token_type,
                contract_id=session.cdr_token.contract_id,
            )
        )

    @staticmethod
    def get_billed_to(session):
        return session.billed_to.party_str() if session.billed_to else ""

    @staticmethod
    def get_location_id(session):
        return session.location.uid

    @staticmethod
    def get_evse_uid(session):
        return session.evse.uid

    @staticmethod
    def get_connector_id(session):
        return (
            session.connector.uid
            if session and hasattr(session, "connector") and session.connector
            else ""
        )


class ConnectorTariffIdSerializer(serializers.Serializer):
    def to_representation(self, instance):
        return instance.uid

    def to_internal_value(self, data):
        tariff = Tariff.objects.filter(uid=data).first()
        if not tariff:
            raise ValidationError(
                f"Tariff {data} is not in the database, please create it before adding Locations"
            )
        return tariff


class EvseSerialnumberSerializer(fields.CharField):
    def to_internal_value(self, evse_uid):
        return find_our_evse(evse_uid)


class TokenIdSerializer(fields.CharField):
    # Find a token with token_id or keep the token_id (for AD HOC tokens)
    def to_internal_value(self, data):
        token = Token.get_if_exists(uid__iexact=data) or data
        return token


class SessionIdSerializer(fields.CharField):
    """To be used only for CPO API, cannot handle overlapping IDs"""

    def to_internal_value(self, data):
        logger.info(f"Got session id {data}")
        if data:
            return Session.objects.get(uid=data.upper())
        return None


class OcppStatusSerializer(fields.ChoiceField):
    def __init__(self, **kwargs):
        super().__init__(choices=OcppStatusChoices.choices, **kwargs)

    def to_internal_value(self, data):
        result = {
            OcppStatusChoices.AVAILABLE: "AVAILABLE",
            OcppStatusChoices.PREPARING: "CHARGING",
            OcppStatusChoices.CHARGING: "CHARGING",
            OcppStatusChoices.SUSPENDEDEV: "CHARGING",
            OcppStatusChoices.SUSPENDEDEVSE: "CHARGING",
            OcppStatusChoices.FINISHING: "CHARGING",
            OcppStatusChoices.RESERVED: "RESERVED",
            OcppStatusChoices.UNAVAILABLE: "CHARGING",
            OcppStatusChoices.FAULTED: "OUTOFORDER",
        }.get(data.upper())
        if not result:
            raise ValidationError(
                f"'{data}' is not a known OCPP status. Options are: {OcppStatusChoices.values}."
            )
        return result


class StatusChangeSerializer(serializers.Serializer):
    evse_uid = EvseSerialnumberSerializer(
        source="evse",
        help_text="The identifier of the device which provides electricity to one or more connectors",
    )
    status = OcppStatusSerializer(
        help_text="The new status of the EVSE, as defined in the OCPP specification"
    )
    timestamp = UTCDateTimeField(
        required=False,
        default_timezone=ZoneInfo("UTC"),
        help_text="Optional timestamp for the status change. Using this field is highly recommended, so that "
        "disruptions in connectivity won't distort status change history. "
        "This will ensure correct billing for the sessions.",
    )


class AuthorizationSerializer(serializers.Serializer):
    evse_id = EvseSerialnumberSerializer(
        source="evse",
        help_text="The identifier of the device which provides electricity to one or more connectors",
    )
    token_id = TokenIdSerializer(
        source="token",
        help_text="The hidden ID of the RFID token, separate from the visual one",
    )


class MeterValuesSerializer(serializers.Serializer):
    """
    The session start and end time are recorded by the system
    """

    session = SessionIdSerializer(
        help_text="The OCPI session ID (from the response of the start_transaction endpoint)",
    )
    kwh = serializers.FloatField(
        help_text="The kWh measurement at the time of this message",
    )
    soc = serializers.FloatField(
        required=False,
        min_value=0,
        max_value=100,
        help_text="The optional State of Charge for the vehicle, if provided by the charge point",
    )
    power = serializers.FloatField(
        required=False,
        help_text="Optional total amount of energy (dis-)charged during this ChargingPeriod: defined in kWh. "
        "When negative, more energy was feed into the grid then charged into the EV. "
        "Default step_size is 1.",
    )
    timestamp = UTCDateTimeField(
        required=False,
        default_timezone=ZoneInfo("UTC"),
        help_text="Optional timestamp for the meter values. Using this field is highly recommended, so that "
        "disruptions in connectivity won't distort cost calculation.",
    )


class StartTransactionSerializer(serializers.Serializer):
    session_id = SessionIdSerializer(
        source="session",
        help_text="The ID of the charging session on the CPO platform, "
        "you get this from the response of a successful authorize request",
    )
    connector_id = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        help_text="The ID of the connector used for charging",
    )
    start_kwh = serializers.FloatField(
        required=False,
        default=0.0,
        help_text="The optional kWh measurement at the meter at start of the transaction, can start from zero "
        "or start from where the previous charging session ended or some other value",
    )
    timestamp = UTCDateTimeField(
        required=False,
        default_timezone=ZoneInfo("UTC"),
        help_text="The timestamp of the moment when the charging session starts, defaults to UTC timezone",
    )


class StopTransactionSerializer(serializers.Serializer):
    """
    The session ends with a specific meter value
    """

    session_id = SessionIdSerializer(
        source="session",
        help_text="The OCPI session ID (from the response of the start_transaction endpoint)",
    )
    stop_kwh = serializers.FloatField(
        min_value=0.0,
        required=True,
        help_text="Optionally, the final kWh reading from the charger",
    )
    timestamp = UTCDateTimeField(
        required=False,
        default_timezone=ZoneInfo("UTC"),
        help_text="The timestamp of the moment when the driver has unplugged the vehicle, defaults to UTC timezone",
    )


class PartyStrField(serializers.CharField):
    def to_internal_value(self, data):
        if isinstance(data, CredentialsRole):
            return data
        if isinstance(data, str):
            if "*" not in data:
                raise ValidationError(
                    f"Invalid format for party ID, expected country_code*party_id, got {data}"
                )
            party = get_credentialsrole(party=Party.from_str(data))
            if not party:
                raise ValidationError(f"No party with id {data}")
            return party
        raise ValidationError(f"Expected a party ID or CredentialsRole, got {data}")

    def to_representation(self, value):
        assert isinstance(
            value, CredentialsRole
        ), f"Expected a CredentialsRole, got {value}"
        return value.party_str()


class CpoOutboundWebhookSerializer(serializers.Serializer):
    response_url = serializers.URLField()
    token_id = serializers.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH)
    token_type = serializers.ChoiceField(choices=TOKEN_TYPE_CHOICES)
    authorization_reference = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        required=False,
        allow_null=True,
        help_text="Optional reference to the authorization given by the eMSP",
    )
    auth_method = serializers.ChoiceField(choices=enum.AUTH_METHOD_CHOICES)
    from_party = serializers.CharField(
        help_text="The ID of the party sending the command"
    )
    evse_id = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, required=False, allow_null=True
    )
    connector_id = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, required=False, allow_null=True
    )
    billed_to = PartyStrField(
        help_text="The party ID of the eMSP that is responsible for paying for the session"
    )


class CommandResponseSerializer(serializers.Serializer):
    timeout = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Timeout for this ChargingProfile request in seconds. "
        "When the Result is not received within this timeout, "
        "the eMSP can assume that the message might never be sent.",
    )
    result = serializers.ChoiceField(
        choices=CommandResultBaseSerializer.RESULT_OPTIONS,
        help_text="The result of the remote command.",
    )


class CPOStartWebhookSerializer(CallbacksSerializer):
    URL = "start_transaction_url"
    start_transaction_url = serializers.URLField()

    class OutboundSerializer(CpoOutboundWebhookSerializer):
        token_type = serializers.ChoiceField(choices=TOKEN_TYPE_CHOICES)
        connector_id = serializers.CharField(
            max_length=settings.OCPI_22_MAX_UID_LENGTH, required=False, allow_null=True
        )

    ResponseSerializer = CommandResponseSerializer


class CPOStopWebhookSerializer(CallbacksSerializer):
    URL = "stop_transaction_url"
    stop_transaction_url = serializers.URLField()

    class OutboundSerializer(CpoOutboundWebhookSerializer):
        token_type = serializers.ChoiceField(choices=TOKEN_TYPE_CHOICES)
        connector_id = serializers.CharField(
            max_length=settings.OCPI_22_MAX_UID_LENGTH, required=False, allow_null=True
        )

    ResponseSerializer = CommandResponseSerializer


class CPOReserveNowWebhookSerializer(CallbacksSerializer):
    URL = "reserve_now_url"
    reserve_now_url = serializers.URLField()

    class OutboundSerializer(CpoOutboundWebhookSerializer):
        expiry_date = UTCDateTimeField()
        location_id = serializers.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH)
        reservation_id = serializers.CharField(
            max_length=settings.OCPI_22_MAX_UID_LENGTH
        )

    ResponseSerializer = CommandResponseSerializer


class VatSerializer(serializers.FloatField):
    key = "vat_percentage"

    def to_representation(self, data) -> float | None:
        return data

    def to_internal_value(self, data):
        if isinstance(data, (float, int)):
            if 0 < data < 1:
                raise ValidationError(
                    "VAT should be the percentage (0-100), not the decimal presentation"
                )
            if not 0 <= data <= 100:
                raise ValidationError("VAT should be a percentage between 0 and 100")
        return data


class CurrencySerializer(serializers.Field):
    key = "currency"

    def to_representation(self, tariff: Tariff) -> str:
        currency = tariff.currency
        if not currency:
            raise ValidationError("Currency must not be None.")
        return currency

    def to_internal_value(self, data: str):
        if not isinstance(data, str):
            raise ValidationError("Currency must be a string value.")

        data = data.strip().upper()

        valid_currencies = get_currency_choices()

        if data not in valid_currencies:
            raise ValidationError(f"Invalid currency value {data}.")

        return {self.key: data}


class PriceSerializer(serializers.DecimalField):
    def to_representation(self, solid_tariff: SolidTariff) -> Decimal:
        return solid_tariff.get_type(self.tariff_type)

    def to_internal_value(self, data):
        result = {self.key: data}
        if result is not None and float(data) < 0:
            raise ValidationError(f"{self.key} cannot be negative.")
        return result


class PriceKwhSerializer(PriceSerializer):
    tariff_type = "ENERGY"
    key = "price_per_kwh"


class PriceMinSerializer(PriceSerializer):
    tariff_type = "TIME_MIN"
    key = "price_per_min"


class PriceHourSerializer(PriceSerializer):
    tariff_type = "TIME_HR"
    key = "price_per_hr"


class PriceFlatSerializer(PriceSerializer):
    tariff_type = "FLAT"
    key = "price_flat"


class ParkingPricePerMinSerializer(PriceSerializer):
    tariff_type = "PARKING_TIME_MIN"
    key = "parking_price_per_min"


class ParkingPricePerHourSerializer(PriceSerializer):
    tariff_type = "PARKING_TIME_HR"
    key = "parking_price_per_hr"


class SolidTariffSerializer(SerializerCleanedUp):
    service = SolidTariffService()
    external_id = serializers.CharField(
        validators=[uid_validator],
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        required=True,
    )
    currency = serializers.ChoiceField(choices=CURRENCY_CHOICES)
    price_per_kwh = PriceKwhSerializer(
        source="*",
        max_digits=8,
        decimal_places=2,
        required=False,
        allow_null=True,
        help_text="The price per kWh of electricity charged excluding tax",
    )
    price_per_min = PriceMinSerializer(
        source="*",
        max_digits=15,
        decimal_places=10,
        required=False,
        allow_null=True,
        help_text="The price per minute of charging, excluding parking and tax",
    )
    price_per_hr = PriceHourSerializer(
        source="*",
        max_digits=12,
        decimal_places=6,
        required=False,
        allow_null=True,
        help_text="The price per hour of charging, excluding parking and tax",
    )
    price_flat = PriceFlatSerializer(
        source="*",
        max_digits=12,
        decimal_places=6,
        required=False,
        allow_null=True,
        help_text="The flat price per started charging session excluding tax",
    )
    parking_price_per_min = ParkingPricePerMinSerializer(
        source="*",
        max_digits=15,
        decimal_places=10,
        required=False,
        allow_null=True,
        help_text="The parking price per min excluding tax",
    )
    parking_price_per_hr = ParkingPricePerHourSerializer(
        source="*",
        max_digits=12,
        decimal_places=6,
        required=False,
        allow_null=True,
        help_text="The parking price per hour excluding tax",
    )
    parking_grace_period = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        help_text="The parking grace period in seconds",
    )
    vat_percentage = VatSerializer(
        required=False,
        allow_null=True,
        help_text="The Value Added Tax amount in percentage",
    )
    msp = PartyStrField(
        help_text="The party ID of the eMSP",
        required=False,
        allow_null=True,
    )
    ocpi_tariff = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        required=False,
        allow_null=True,
        help_text="The OCPI identifier of the tariff",
    )
    last_updated = UTCDateTimeField(required=False)


class CPOAuthorizationResponseSerializer(serializers.Serializer):
    allowed = serializers.ChoiceField(choices=AuthorizationEnum.choices)
    token = serializers.SerializerMethodField()
    authorization_reference = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        help_text="The unique reference of the authorization, provided by the eMSP",
    )
    responding_party = serializers.CharField(max_length=5)
    billed_to = serializers.CharField(
        max_length=5,
        help_text="The identifier of the eMSP that is responsible for paying for the session",
    )
    auth_method = serializers.ChoiceField(choices=enum.AUTH_METHOD_CHOICES)
    session_id = serializers.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH)

    @staticmethod
    def get_token(authorization):
        token = authorization.get("token")
        if not token:
            return ""
        return token.uid if isinstance(token, Token) else token
