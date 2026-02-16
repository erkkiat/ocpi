"""
DirectPayment Module Serializers

OCPI 2.2.1 EVRF DirectPayment extension serializers.
Reference: DirectPayment_2_2_1___EVRF_version.pdf (March 2024)

Design Philosophy:
- Use ModelSerializer for automatic field mapping
- Custom fields handle nested object transformation
- Clean separation: transformation in to_internal_value(), validation in validate()
- No data mutation in validate() methods
- Use DRF ValidationError with specific error codes for better error handling
"""

from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError

from generic.validators import validate_latitude, validate_longitude
from ocpi22.payments.models import Terminal, FinancialAdviceConfirmation
from ocpi22.payments.validators import validate_currency_code


class CoordinatesField(serializers.Field):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                "Coordinates must be an object", code="invalid_coordinates_type"
            )

        latitude = data.get("latitude")
        longitude = data.get("longitude")

        if latitude and not longitude:
            raise serializers.ValidationError(
                {"longitude": "This field is required when latitude is provided"},
                code="missing_longitude",
            )

        if longitude and not latitude:
            raise serializers.ValidationError(
                {"latitude": "This field is required when longitude is provided"},
                code="missing_latitude",
            )

        if not latitude and not longitude:
            return None

        errors = {}
        try:
            validate_latitude(latitude)
        except DjangoValidationError as exc:
            errors["latitude"] = exc.messages

        try:
            validate_longitude(longitude)
        except DjangoValidationError as exc:
            errors["longitude"] = exc.messages

        if errors:
            raise serializers.ValidationError(errors)

        return {"latitude": latitude, "longitude": longitude}

    def to_representation(self, value):
        if isinstance(value, dict):
            lat = value.get("latitude")
            lon = value.get("longitude")
        else:
            return None

        if lat and lon:
            return {"latitude": lat, "longitude": lon}
        return None


class TotalCostField(serializers.Field):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                "total_cost must be an object", code="invalid_total_cost_type"
            )

        excl_vat = data.get("excl_vat")
        incl_vat = data.get("incl_vat")
        currency = data.get("currency")

        errors = {}

        if excl_vat is None:
            errors["excl_vat"] = ["This field is required"]

        if currency is None:
            errors["currency"] = ["This field is required"]

        if errors:
            raise serializers.ValidationError(errors)

        validated_excl_vat = None
        validated_incl_vat = None

        try:
            validated_excl_vat = float(excl_vat)
        except (ValueError, TypeError):
            errors["excl_vat"] = [f"'{excl_vat}' is not a valid number"]

        if incl_vat is not None:
            try:
                validated_incl_vat = float(incl_vat)
            except (ValueError, TypeError):
                errors["incl_vat"] = [f"'{incl_vat}' is not a valid number"]

        try:
            validate_currency_code(currency)
        except DjangoValidationError as exc:
            errors["currency"] = exc.messages

        if errors:
            raise serializers.ValidationError(errors)

        return {
            "excl_vat": validated_excl_vat,
            "incl_vat": validated_incl_vat,
            "currency": currency,
        }

    def to_representation(self, value):
        return None


class TerminalSerializer(serializers.ModelSerializer):
    coordinates = serializers.SerializerMethodField()
    location_ids = serializers.SerializerMethodField()
    evse_uids = serializers.SerializerMethodField()

    class Meta:
        model = Terminal
        fields = [
            "terminal_id",
            "customer_reference",
            "party_id",
            "country_code",
            "address",
            "city",
            "postal_code",
            "state",
            "country",
            "coordinates",
            "invoice_base_url",
            "invoice_creator",
            "location_ids",
            "evse_uids",
            "last_updated",
        ]

    def get_coordinates(self, obj):
        if obj.latitude and obj.longitude:
            return {
                "latitude": obj.latitude,
                "longitude": obj.longitude,
            }
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if data.get("coordinates") is None:
            data.pop("coordinates", None)
        return data

    def get_location_ids(self, obj):
        return obj.location_ids

    def get_evse_uids(self, obj):
        return obj.evse_uids


class TerminalWriteSerializer(serializers.ModelSerializer):
    coordinates = CoordinatesField(required=False, allow_null=True)
    location_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        write_only=True,
    )
    evse_uids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        write_only=True,
    )

    class Meta:
        model = Terminal
        fields = [
            "terminal_id",
            "customer_reference",
            "party_id",
            "country_code",
            "address",
            "city",
            "postal_code",
            "state",
            "country",
            "coordinates",
            "invoice_base_url",
            "invoice_creator",
            "location_ids",
            "evse_uids",
        ]

    def to_internal_value(self, data):
        validated_data = super().to_internal_value(data)

        if "coordinates" in validated_data:
            coord_data = validated_data.pop("coordinates")

            if coord_data is not None:
                validated_data["latitude"] = coord_data["latitude"]
                validated_data["longitude"] = coord_data["longitude"]

        return validated_data


class FinancialAdviceConfirmationSerializer(serializers.ModelSerializer):
    total_cost = serializers.SerializerMethodField()

    class Meta:
        model = FinancialAdviceConfirmation
        fields = [
            "fac_id",
            "authorization_reference",
            "total_cost",
            "eft_data",
            "capture_status_code",
            "capture_status_message",
            "last_updated",
        ]

    def get_total_cost(self, obj):
        if obj.total_cost_excl_vat is not None and obj.currency:
            result = {
                "excl_vat": obj.total_cost_excl_vat,
                "currency": obj.currency,
            }
            if obj.total_cost_incl_vat is not None:
                result["incl_vat"] = obj.total_cost_incl_vat
            return result
        return None


class FinancialAdviceConfirmationWriteSerializer(serializers.ModelSerializer):
    total_cost = TotalCostField(required=True)

    class Meta:
        model = FinancialAdviceConfirmation
        fields = [
            "fac_id",
            "authorization_reference",
            "total_cost",
            "eft_data",
            "capture_status_code",
            "capture_status_message",
            "last_updated",
        ]

    def to_internal_value(self, data):
        validated_data = super().to_internal_value(data)

        if "total_cost" in validated_data and validated_data["total_cost"]:
            cost_data = validated_data.pop("total_cost")

            validated_data["total_cost_excl_vat"] = cost_data["excl_vat"]
            validated_data["total_cost_incl_vat"] = cost_data.get("incl_vat")
            validated_data["currency"] = cost_data["currency"]

        return validated_data

    def validate(self, attrs):
        return attrs


class GeoLocationSerializer(serializers.Serializer):
    latitude = serializers.CharField(
        max_length=10,
        validators=[validate_latitude],
    )
    longitude = serializers.CharField(
        max_length=11,
        validators=[validate_longitude],
    )


class PriceSerializer(serializers.Serializer):
    excl_vat = serializers.FloatField()
    incl_vat = serializers.FloatField(required=False, allow_null=True)
    currency = serializers.CharField(
        max_length=3,
        validators=[validate_currency_code],
    )
