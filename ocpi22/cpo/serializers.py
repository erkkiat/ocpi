from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Union
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from rest_framework import serializers, fields
from rest_framework.exceptions import ValidationError

from ocpi22.choices import (
    OcppStatusChoices,
    TOKEN_TYPE_CHOICES,
    AuthorizationEnum,
    OcpiRolesEnum,
)
from ocpi22.commands.serializers import CommandResultBaseSerializer
from ocpi22.cpo.util import _find_our_evse
from ocpi22.models import enum
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.location import Evse, Connector, Location
from ocpi22.models.session import Session
from ocpi22.models.tariff import Tariff, TariffElement, PriceComponent, SolidTariff
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
    fill_out_location_address,
    get_currency_choices,
)
from ocpiconnector.ocpi_identities import (
    get_our_country_code,
    get_our_party_id,
    get_our_party,
)
from ocpiconnector.party import Party


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
                token_id=session.cdr_token_uid,
                type=session.cdr_token_type,
                contract_id=session.cdr_token_contract_id,
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


class ConnectorQuickSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Connector
        fields = [
            "uid",
            "standard",
            "format",
            "max_voltage",
            "max_amperage",
            "max_electric_power",
            "tariff_ids",
            "last_updated",
        ]

    uid = serializers.CharField(
        validators=[uid_validator], max_length=settings.OCPI_22_MAX_UID_LENGTH
    )
    tariff_ids = ConnectorTariffIdSerializer(required=False, many=True)
    last_updated = UTCDateTimeField(required=False)


class EvseQuickSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Evse
        fields = ["status_url", "uid", "connectors", "last_updated"]

    uid = serializers.CharField(
        validators=[uid_validator], max_length=settings.OCPI_22_MAX_UID_LENGTH
    )
    connectors = ConnectorQuickSerializer(many=True)
    last_updated = UTCDateTimeField(required=False)


class LocationQuickSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Location
        fields = [
            "quick_url",
            "id",
            "name",
            "language",
            "address",
            "city",
            "postal_code",
            "state",
            "country",
            "time_zone",
            "latitude",
            "longitude",
            "evses",
            "last_updated",
        ]

    id = serializers.CharField(
        source="uid",
        validators=[uid_validator],
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
    )
    evses = EvseQuickSerializer(many=True, required=False)
    language = serializers.CharField(
        required=False,
        max_length=6,
        help_text="Optional language of the location address, if address is determined based on coordinates",
    )
    address = serializers.CharField(
        required=False,
        max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH,
        help_text="If omitted, street address will be determined automatically based on coordinates",
    )
    city = serializers.CharField(
        required=False,
        max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH,
        help_text="If omitted, city will be determined automatically based on coordinates",
    )
    country = serializers.CharField(
        required=False,
        max_length=3,
        help_text="If omitted, country will be determined automatically based on coordinates",
    )
    latitude = serializers.FloatField(required=False)
    longitude = serializers.FloatField(required=False)
    time_zone = serializers.CharField(
        required=False,
        max_length=settings.OCPI_22_MAX_TIME_ZONE_LENGTH,
        help_text="If omitted, time zone will be determined automatically based on coordinates",
    )
    lookup_field = "uid"
    last_updated = UTCDateTimeField(required=False)

    def create(self, validated_data, *args, **kwargs):
        evses = validated_data.pop("evses", [])
        validated_data = fill_out_location_address(
            validated_data,
            validated_data.get("latitude"),
            validated_data.get("longitude"),
        )
        location = Location.objects.create(**validated_data)
        for evse_dict in evses:
            connectors = evse_dict.pop("connectors", [])
            evse = Evse.objects.create(location=location, **evse_dict)
            for connector_dict in connectors:
                tariff_ids = connector_dict.pop("tariff_ids", None)
                connector = Connector.objects.create(evse=evse, **connector_dict)
                if tariff_ids:
                    connector.tariff_ids.set(tariff_ids)
                else:
                    connector.tariff_ids.clear()
        return location

    def update(self, location, validated_data, *args, **kwargs):
        evses = validated_data.pop("evses", [])
        validated_data = fill_out_location_address(
            validated_data,
            validated_data.get("latitude"),
            validated_data.get("longitude"),
        )
        Location.objects.filter(uid__iexact=location.uid).update(**validated_data)
        for evse_dict in evses:
            connectors = evse_dict.pop("connectors", [])
            evse, created = Evse.objects.get_or_create(
                location=location, uid__iexact=evse_dict.get("uid"), defaults=evse_dict
            )
            if not created:
                Evse.objects.filter(uid__iexact=evse.uid).update(**evse_dict)
            for connector_dict in connectors:
                tariff_ids = connector_dict.pop("tariff_ids", None)
                connector, created = Connector.objects.get_or_create(
                    evse=evse, uid=connector_dict.pop("uid"), defaults=connector_dict
                )
                if not created:
                    Connector.objects.filter(
                        uid__iexact=connector.uid, evse=evse
                    ).update(**connector_dict)
                if tariff_ids:
                    connector.tariff_ids.set(tariff_ids)
        return location


class EvseSerialnumberSerializer(fields.CharField):
    def to_internal_value(self, evse_uid):
        return _find_our_evse(evse_uid)


class TokenIdSerializer(fields.CharField):
    # Find a token with token_id or keep the token_id (for AD HOC tokens)
    def to_internal_value(self, data):
        token = Token.get_if_exists(uid__iexact=data) or data
        return token


class SessionIdSerializer(fields.CharField):
    """To be used only for CPO API, cannot handle overlapping IDs"""

    def to_internal_value(self, data):
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

    session_id = SessionIdSerializer(
        source="session",
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
        required=False,
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
    stop_kwh = serializers.DecimalField(
        max_digits=8,
        decimal_places=4,
        required=False,
        help_text="Optionally, the final kWh reading from the charger",
    )
    timestamp = UTCDateTimeField(
        required=False,
        default_timezone=ZoneInfo("UTC"),
        help_text="The timestamp of the moment when the driver has unplugged the vehicle, defaults to UTC timezone",
    )


class PartyStrField(serializers.CharField):
    def to_internal_value(self, data):
        from ocpi22.models.credentials import CredentialsRole

        if isinstance(data, CredentialsRole):
            return data
        if isinstance(data, str):
            if "*" not in data:
                raise ValidationError(
                    f"Invalid format for party ID, expected country_code*party_id, got {data}"
                )
            party = get_credentialsrole(party=Party(*data.split("*")))
            if not party:
                raise ValidationError(f"No party with id {data}")
            return party
        raise ValidationError(f"Expected a party ID or CredentialsRole, got {data}")

    def to_representation(self, value):
        from ocpi22.models.credentials import CredentialsRole

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

    def to_representation(self, tariff: Tariff) -> Union[int, str]:
        pe = tariff.tariff_elements.first()
        # Iterate through the VATs for this Tariff and check if there are multiple different ones
        vats = set(pe.price_components.values_list("vat", flat=True))
        if len(vats) == 1:
            return vats.pop()
        return "Multiple"

    def to_internal_value(self, data):
        if isinstance(data, (float, int)):
            if 0 < data < 1:
                raise ValidationError(
                    "VAT should be the percentage (0-100), not the decimal presentation"
                )
            if not 0 <= data <= 100:
                raise ValidationError("VAT should be a percentage between 0 and 100")
        return {self.key: data}


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
    def to_representation(self, tariff: Tariff) -> Decimal:
        pc = tariff.get_type(self.tariff_type)
        return pc.price if pc else None

    def to_internal_value(self, data):
        result = {self.key: data}
        return result


class PriceKwhSerializer(PriceSerializer):
    tariff_type = "ENERGY"
    key = "price_per_kwh"


class PriceMinSerializer(PriceSerializer):
    tariff_type = "TIME"
    key = "price_per_min"


class PriceFlatSerializer(PriceSerializer):
    tariff_type = "FLAT"
    key = "price_flat"


class SolidTariffSerializer(SerializerCleanedUp):
    id = serializers.CharField(
        source="uid",
        validators=[uid_validator],
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
    )
    currency = serializers.ChoiceField(choices=CURRENCY_CHOICES, default="EUR")
    price_per_kwh = PriceKwhSerializer(
        source="*",
        max_digits=8,
        decimal_places=4,
        required=False,
        help_text="The price per kWh of electricity charged excluding tax",
    )
    price_per_min = PriceMinSerializer(
        source="*",
        max_digits=8,
        decimal_places=4,
        required=False,
        help_text="The price per minute of charging, excluding parking and tax",
    )
    price_flat = PriceFlatSerializer(
        source="*",
        max_digits=8,
        decimal_places=4,
        required=False,
        help_text="The flat price per started charging session excluding tax",
    )
    vat_percentage = VatSerializer(
        source="*",
        required=False,
        allow_null=True,
        help_text="The Value Added Tax amount in percentage",
    )
    msps = serializers.ListField(child=PartyStrField(), required=False)

    def create(self, validated_data):
        def create_solid_tariffs():
            msps = set(validated_data.get("msps", []))
            operator_country_code = get_our_country_code(OcpiRolesEnum.CPO.value)
            operator_party_id = get_our_party_id(OcpiRolesEnum.CPO.value)
            operator = CredentialsRole.get_if_exists(
                country_code=operator_country_code, party_id=operator_party_id
            )
            if operator is None:
                raise ValueError(
                    f"Operator : {operator_country_code}*{operator_party_id} does not exist"
                )

            solid_tariffs = [
                SolidTariff(
                    uid=validated_data.get("uid"),
                    currency=currency,
                    price_per_kwh=per_kwh,
                    price_per_min=per_min,
                    price_flat=flat,
                    vat_percentage=vat,
                    msp=msp if msp else None,
                    operator=operator,
                    last_updated=datetime.now(),
                )
                for msp in (msps or [None])
            ]

            SolidTariff.objects.bulk_create(solid_tariffs)

        with transaction.atomic():
            currency = validated_data.get(CurrencySerializer.key)

            tariff = Tariff.objects.create(
                uid=validated_data.get("uid"),
                ocpi_master=validated_data.get("ocpi_master"),
                currency=currency,
            )
            te = TariffElement.objects.create(tariff=tariff)
            per_kwh = validated_data.get(PriceKwhSerializer.key)
            per_min = validated_data.get(PriceMinSerializer.key)
            flat = validated_data.get(PriceFlatSerializer.key)
            vat = validated_data.get(VatSerializer.key)

            if per_kwh:
                PriceComponent.objects.create(
                    tariff_element=te,
                    type="ENERGY",
                    price=per_kwh,
                    vat=vat,
                    step_size=1,
                )
            if per_min:
                PriceComponent.objects.create(
                    tariff_element=te, type="TIME", price=per_min, vat=vat, step_size=1
                )
            if flat:
                PriceComponent.objects.create(
                    tariff_element=te, type="FLAT", price=flat, vat=vat, step_size=1
                )

            create_solid_tariffs()
        return tariff

    def update(self, tariff: Tariff, validated_data: dict):
        def update_price_components(price, tariff_type) -> None:
            data = dict(price=price, vat=vat, step_size=1)
            pc, created = PriceComponent.objects.get_or_create(
                tariff_element=te, type=tariff_type, defaults=data
            )
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
            (per_kwh, "ENERGY"),
            (per_min, "TIME"),
            (flat, "FLAT"),
        )
        for price, tariff_type in price_components:
            if price is not None:
                update_price_components(price, tariff_type)

        if vat is not None:
            te.price_components.update(vat=vat)

        self.update_solid_tariff(tariff, validated_data)

        return tariff

    def update_solid_tariff(self, tariff: Tariff, validated_data: dict):
        party: Party = get_our_party(OcpiRolesEnum.CPO)
        operator = CredentialsRole.get_if_exists(
            country_code=party.country_code, party_id=party.party_id
        )
        if operator is None:
            raise ValueError(
                f"Operator : {party.country_code}*{party.party_id} does not exist"
            )

        solid_tariffs = SolidTariff.objects.filter(uid=tariff.uid, archived=False)

        per_kwh = validated_data.get(PriceKwhSerializer.key)
        per_min = validated_data.get(PriceMinSerializer.key)
        flat = validated_data.get(PriceFlatSerializer.key)
        vat = validated_data.get(VatSerializer.key)
        currency = validated_data.get(CurrencySerializer.key)

        fields_to_update = {
            "price_per_kwh": per_kwh,
            "price_per_min": per_min,
            "price_flat": flat,
            "currency": currency,
            "vat_percentage": vat,
        }

        msp_tariff_map = defaultdict(list)
        current_saved_msps = set()

        for solid_tariff in solid_tariffs:
            for field, value in fields_to_update.items():
                if value is not None:
                    setattr(solid_tariff, field, value)

            if solid_tariff.msp:
                msp_tariff_map[solid_tariff.msp.party_str()].append(solid_tariff)
                current_saved_msps.add(solid_tariff.msp)

            solid_tariff.last_updated = datetime.now()
            solid_tariff.archived = False

        msps = validated_data.get("msps")

        if msps is not None:
            if len(msps) == 0:
                for i, solid_tariff in enumerate(solid_tariffs):
                    solid_tariff.msp = None
                    # Delete all redundant records
                    if i != 0:
                        solid_tariff.archived = True
            else:
                new_msps = set(msps)

                msps_to_add = new_msps - current_saved_msps
                msps_to_remove = current_saved_msps - new_msps

                for solid_tariff in solid_tariffs:
                    if solid_tariff.msp is None:
                        solid_tariff.msp = msps_to_add.pop()
                    elif solid_tariff.msp in msps_to_remove:
                        solid_tariff.archived = True

                new_solid_tariffs = [
                    SolidTariff(
                        uid=tariff.uid,
                        price_per_kwh=fields_to_update.get("price_per_kwh"),
                        price_per_min=fields_to_update.get("price_per_min"),
                        price_flat=fields_to_update.get("price_flat"),
                        currency=fields_to_update.get("currency"),
                        vat_percentage=fields_to_update.get("vat"),
                        archived=False,
                        msp=msp,
                        operator=operator,
                        last_updated=datetime.now(),
                    )
                    for msp in msps_to_add
                ]
                SolidTariff.objects.bulk_create(new_solid_tariffs)

        SolidTariff.objects.bulk_update(
            solid_tariffs,
            fields=list(fields_to_update.keys()) + ["last_updated", "msp", "archived"],
        )


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
