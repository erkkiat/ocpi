from logging import getLogger

from django.db import transaction
from django.db.transaction import atomic
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from ocpi22.choices import OCPIFacility, OCPICapability
from ocpi22.locations.util import get_or_create_business_details
from ocpi22.models.business_details import BusinessDetails
from ocpi22.models.image import OCPIImage
from ocpi22.models.location import Connector, Evse, Location
from ocpi22.models.tariff import Tariff
from ocpi22.models.token import Token
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.util import Ocpi
from ocpi22.serializers.hours import HoursSerializer
from ocpi22.util import uid_validator, CiStringField
from ocpi22.serializers.util import (
    HyperlinkedModelSerializerCleanedUp,
    UTCDateTimeField,
)
from ocpiconnector.party import Party

logger = getLogger(__name__)


class OCPIImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = OCPIImage
        fields = ["url", "thumbnail", "category", "type", "width", "height"]

    type = CiStringField(max_length=4, source="image_type")


class BusinessDetailsSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = BusinessDetails
        fields = ["name", "website", "logo"]

    logo = OCPIImageSerializer(required=False, allow_null=True)

    def create(self, data):
        if isinstance(data, BusinessDetails) or not data:
            return data

        return get_or_create_business_details(**data)


class PowerTypeSerializer(serializers.ChoiceField):
    def __init__(self, **kwargs):
        kwargs["choices"] = Ocpi.POWERTYPE_CHOICES_221
        super().__init__(**kwargs)

    def to_representation(self, power_type):
        version = self.context.get("version", None)  # Action required only for OCPI 2.2
        if version == "2.2":
            power_type = dict(
                AC_2_PHASE="AC_1_PHASE",
                AC_2_PHASE_SPLIT="AC_1_PHASE",
            ).get(power_type, power_type)
        return super().to_representation(power_type)


class TariffField(serializers.StringRelatedField):
    def to_internal_value(self, data):
        try:
            credentialsrole = self.context.get(
                "credentialsrole",
                getattr(self.context.get("request", object), "credentialsrole", None),
            )
            assert (
                credentialsrole
            ), "No credentialsrole found in the context in TariffField"
            tariff = Tariff.objects.get_cached(
                uid__iexact=data, archived=False, ocpi_master=credentialsrole
            )
            return tariff
        except Tariff.DoesNotExist:
            raise ValidationError(f"Tariff with UID `{data}` cannot be fetched.")
        except Tariff.MultipleObjectsReturned:
            logger.error(
                f"Multiple tariffs found with UID `{data}` and ocpi_master `{credentialsrole}`."
            )
            raise ValidationError(f"Tariff with UID `{data}` cannot be fetched.")

    def to_representation(self, value: Tariff):
        return value.uid


class CommaSeparatedChoiceField(serializers.ChoiceField):
    def __init__(self, choices, **kwargs):
        super().__init__(choices=choices, **kwargs)

    def to_representation(self, value):
        if isinstance(value, str):
            values = value.split(",")
        else:
            values = value
        values = [v for v in values if v]  # Remove empty strings
        result = super().to_representation(values)
        return result

    def to_internal_value(self, data):
        if isinstance(data, list):
            data = ",".join(data)
        values = data.split(",")
        for value in values:
            if value not in self.choices:
                raise serializers.ValidationError(_("Invalid value '%s'.") % value)
        return data


class FacilityField(CommaSeparatedChoiceField):
    def __init__(self, **kwargs):
        super().__init__(choices=OCPIFacility.choices, **kwargs)


class CapabilityField(CommaSeparatedChoiceField):
    def __init__(self, **kwargs):
        super().__init__(choices=OCPICapability.choices, **kwargs)


class MaxElectricPowerSerializer(serializers.IntegerField):
    def to_representation(self, connector):
        assert isinstance(connector, Connector)  # Must use source='*'
        phases = Ocpi.POWERTYPE_PHASES.get(connector.power_type, 1)
        return (
            connector.max_electric_power
            or connector.max_voltage * connector.max_amperage * phases
        )

    def to_internal_value(self, data):
        return dict(max_electric_power=data)


class UpdateMixin:
    def update_last_updated(self, instance, last_updated):
        if instance:
            instance.last_updated = last_updated
            instance.save()
            if instance and hasattr(instance, "parent"):
                self.update_last_updated(instance.parent, last_updated)


class ConnectorSerializer(HyperlinkedModelSerializerCleanedUp, UpdateMixin):
    class Meta:
        model = Connector
        fields = [
            "id",
            "standard",
            "format",
            "power_type",
            "max_voltage",
            "max_amperage",
            "max_electric_power",
            "tariff_ids",
            "terms_and_conditions",
            "last_updated",
        ]

    id = serializers.CharField(source="uid")
    tariff_ids = TariffField(many=True, required=False)
    last_updated = UTCDateTimeField()
    power_type = PowerTypeSerializer()
    max_electric_power = MaxElectricPowerSerializer(source="*", required=False)

    def save(self, **kwargs):
        self.update_last_updated(self.instance, self.validated_data.get("last_updated"))
        return super().save(**kwargs)


class EvseSerializer(HyperlinkedModelSerializerCleanedUp, UpdateMixin):
    class Meta:
        model = Evse
        fields = [
            "detail_url",
            "uid",
            "evse_id",
            "status",
            "last_updated",
            "connectors",
            "capabilities",
        ]

    lookup_field = "uid"

    connectors = ConnectorSerializer(many=True, required=True)
    uid = serializers.CharField(validators=[uid_validator])
    capabilities = CapabilityField(required=False)
    last_updated = UTCDateTimeField(required=False)

    def save(self, **kwargs):
        self.update_last_updated(self.instance, self.validated_data.get("last_updated"))
        return super().save(**kwargs)

    def to_representation(self, evse: Evse):
        result = super().to_representation(evse)
        version = self.context.get("version", None)
        if version == "2.2" and "capabilities" in result:
            try:
                result["capabilities"].remove(
                    "START_SESSION_CONNECTOR_REQUIRED"
                )  # Not supported in OCPI 2.2
            except ValueError:
                pass  # Ok, no such capability in this EVSE anyway
        return result

    @staticmethod
    def process_connectors(evse: Evse, connectors: dict) -> None:
        for c in connectors:
            tariff_ids = c.pop("tariff_ids", [])
            try:
                connector = Connector.objects.get(uid=c.get("uid"), evse=evse)
                for key, value in c.items():
                    if key != "uid":
                        setattr(connector, key, value)
                connector.tariff_ids.set(tariff_ids)
                connector.save()
            except Connector.DoesNotExist:
                connector = Connector.objects.create(evse=evse, **c)
                connector.tariff_ids.set(tariff_ids)

    def create(self, validated_data):
        connectors = validated_data.pop("connectors", [])
        capabilities = validated_data.pop("capabilities", [])
        evse = Evse.objects.create(**validated_data)
        evse.capabilities.set(capabilities)
        self.process_connectors(evse, connectors)
        return evse

    def update(self, evse: Evse, validated_data: dict) -> Evse:
        skip_fields = {"evse_id", "uid"}

        connectors = validated_data.pop("connectors", [])
        self.process_connectors(evse, connectors)

        # Todo: map() or [] instead of for loop
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
            raise ValidationError(
                f"Unable to find token with {str(data)}. Try to send the Token to us first."
            )
        return token

    def to_representation(self, token: Token) -> dict:
        return dict(uid=token.uid, issuer=token.issuer)


class LocationSerializer221(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Location
        fields = [
            "detail_url",
            "country_code",
            "party_id",
            "id",
            "publish",
            "publish_allowed_to",
            "name",
            "address",
            "city",
            "postal_code",
            "state",
            "country",
            "coordinates",
            "parking_type",
            "evses",
            "operator",
            "suboperator",
            "owner",
            "facilities",
            "opening_times",
            "charging_when_closed",
            "time_zone",
            "last_updated",
            "roaming_enabled",
        ]

    lookup_field = "uid"

    id = serializers.CharField(source="uid")
    country_code = serializers.CharField(source="ocpi_master.country_code")
    party_id = serializers.CharField(source="ocpi_master.party_id")

    evses = EvseSerializer(many=True, required=False)
    coordinates = CoordinatesSerializer()
    facilities = FacilityField(required=False)
    owner = BusinessDetailsSerializer(required=False)
    operator = BusinessDetailsSerializer(required=False)
    suboperator = BusinessDetailsSerializer(required=False)
    last_updated = UTCDateTimeField(required=False)
    publish_allowed_to = PublishAllowedToSerializer(many=True, required=False)
    opening_times = HoursSerializer(required=False)

    @staticmethod
    def process_coordinates(validated_data: dict):
        """Handle manually all subobjects the Location cannot handle"""
        coordinates = validated_data.pop("coordinates", None)
        if coordinates:
            validated_data["latitude"] = coordinates.get("latitude")
            validated_data["longitude"] = coordinates.get("longitude")
        return validated_data

    @staticmethod
    def process_ocpi_master(validated_data: dict):
        if isinstance(validated_data, dict):
            ocpi_master_data = validated_data.get("ocpi_master", validated_data)
            if isinstance(ocpi_master_data, dict):
                country_code = ocpi_master_data.get("country_code")
                party_id = ocpi_master_data.get("party_id")
                ocpi_master = get_credentialsrole(
                    None, party=Party(country_code, party_id), create=True
                )
                validated_data["ocpi_master"] = ocpi_master
        return validated_data

    def to_representation(self, validated_data: dict):
        if isinstance(validated_data, dict):
            validated_data = self.process_coordinates(validated_data)
        return super().to_representation(validated_data)

    @staticmethod
    def update_evse(evse, data, location):
        for key, value in data.items():
            if key not in {"uid", "evse_id"}:
                setattr(evse, key, value)
        existing_location = evse.location
        if existing_location != location:
            evse.location = location
            logger.info(
                f"Moved evse {evse.uid} from {existing_location.uid} to {location.uid}"
            )
        evse.save()

    @staticmethod
    def update_connector(connector, data):
        for key, value in data.items():
            if key != "uid":
                setattr(connector, key, value)
        connector.save()

    def create(self, validated_data: dict):
        with transaction.atomic():
            validated_data = self.process_coordinates(validated_data)
            validated_data = self.process_ocpi_master(validated_data)
            evses = validated_data.pop("evses", [])
            opening_times = validated_data.pop("opening_times", None)
            publish_allowed_to = validated_data.pop("publish_allowed_to", [])
            operator = BusinessDetailsSerializer().create(
                data=validated_data.pop("operator", None)
            )
            suboperator = BusinessDetailsSerializer().create(
                data=validated_data.pop("suboperator", None)
            )
            owner = BusinessDetailsSerializer().create(
                data=validated_data.pop("owner", None)
            )

            location = Location.objects.create(
                **validated_data,
                operator=operator,
                suboperator=suboperator,
                owner=owner,
            )
            location.publish_allowed_to.set(publish_allowed_to)

            for e in evses:
                connectors = e.pop("connectors", [])
                evse = Evse.get_if_exists(
                    uid__iexact=e.get("uid"),
                    location__ocpi_master=location.ocpi_master,
                )
                if evse:
                    self.update_evse(evse, e, location)
                else:
                    evse = Evse.objects.create(**e, location=location)

                for c in connectors:
                    tariff_ids = c.pop("tariff_ids", [])
                    connector = Connector.get_if_exists(
                        uid__iexact=c.get("uid"), evse=evse
                    )
                    if connector:
                        self.update_connector(connector, c)
                    else:
                        connector = Connector.objects.create(**c, evse=evse)

                    tariffs = []
                    for t in tariff_ids:
                        try:
                            tariff = Tariff.objects.get(
                                uid=t,
                                ocpi_master__country_code=location.ocpi_master.country_code,
                                ocpi_master__party_id=location.ocpi_master.party_id,
                                archived=False,
                            )
                            tariffs.append(tariff)
                        except Tariff.DoesNotExist:
                            # Todo: Fetch Tariffs from other party
                            raise ValidationError(
                                f"Tariff `{t}` for {location.ocpi_master.country_code}*"
                                f"{location.ocpi_master.party_id} does not exist in our database"
                            )
                    connector.tariff_ids.set(tariffs)

            if opening_times:
                serializer = HoursSerializer(data=opening_times)
                if serializer.is_valid():
                    hours = serializer.save()
                    location.opening_times = hours
                else:
                    raise ValidationError(serializer.errors)

            return location

    @atomic
    def update(self, location: Location, validated_data: dict) -> Location:
        readonly_fields = {
            "country_code",
            "party_id",
            "uid",
        }  # Lookups in set are faster

        # Pop out all elements which are not directly understood by Location, and process them separately
        validated_data = self.process_coordinates(validated_data)
        validated_data = self.process_ocpi_master(validated_data)
        evses = validated_data.pop("evses", [])
        opening_times = validated_data.pop("opening_times", None)
        publish_allowed_to = validated_data.pop("publish_allowed_to", [])
        location.operator = BusinessDetailsSerializer().create(
            data=validated_data.pop("operator", None)
        )
        location.suboperator = BusinessDetailsSerializer().create(
            data=validated_data.pop("suboperator", None)
        )
        location.owner = BusinessDetailsSerializer().create(
            data=validated_data.pop("owner", None)
        )
        location.publish_allowed_to.set(publish_allowed_to)

        for key, value in validated_data.items():
            if key not in readonly_fields:
                setattr(location, key, value)

        location.save()

        for e in evses:
            connectors = e.pop("connectors", [])
            evse = Evse.get_if_exists(
                uid__iexact=e.get("uid"), location__ocpi_master=location.ocpi_master
            ) or Evse.get_if_exists(uid__iexact=e.get("uid"), location=location)
            if evse:
                self.update_evse(evse, e, location)
            else:
                evse = Evse.objects.create(**e, location=location)

            for c in connectors:
                tariff_ids = c.pop("tariff_ids", [])
                connector = Connector.get_if_exists(uid__iexact=c.get("uid"), evse=evse)
                if connector:
                    self.update_connector(connector, c)
                else:
                    connector = Connector.objects.create(**c, evse=evse)
                connector.tariff_ids.set(tariff_ids)

        if opening_times:
            if hasattr(location, "opening_times"):
                HoursSerializer().update(location.opening_times, opening_times)
            else:
                HoursSerializer().create(opening_times, location=location)
                # location.opening_times = opening_times_instance
                # location.save()

        # # Opening times
        # if opening_times:
        #     if location.opening_times:
        #         location.opening_times.all().delete()
        #     serializer = HoursSerializer(data=opening_times)
        #     if serializer.is_valid():
        #         hours = serializer.save()
        #         location.opening_times = hours
        #         location.save(update_fields=['opening_times'])
        #     else:
        #         raise ValidationError(serializer.errors)

        return location


class LocationSerializer(LocationSerializer221):
    class Meta:
        model = Location
        fields = [
            "detail_url",
            "country_code",
            "party_id",
            "id",
            "publish",
            "publish_allowed_to",
            "name",
            "address",
            "city",
            "postal_code",
            "country",
            "coordinates",
            "parking_type",
            "evses",
            "operator",
            "suboperator",
            "owner",
            "facilities",
            "time_zone",
            "last_updated",
        ]
