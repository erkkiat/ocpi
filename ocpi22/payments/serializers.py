"""
DirectPayment Module Serializers

OCPI 2.2.1 EVRF DirectPayment extension serializers.
Reference: DirectPayment_2_2_1___EVRF_version.pdf (March 2024)

Design Philosophy:
- Single ModelSerializer per object handles both incoming and outgoing directions.
- Nested wire objects (coordinates, total_costs) are validated by dedicated nested
  Serializer classes (GeoLocationSerializer, PriceSerializer). These live at the
  bottom of this module and are the single source of truth for field constraints.
- to_internal_value() on each ModelSerializer unpacks the validated nested dict into
  flat model fields (latitude/longitude, total_cost_excl_vat/incl_vat). This is the
  only transformation logic; no manual type coercion or error building lives here.
- to_representation() re-packs flat model fields back to spec-compliant nested shape.
- No data mutation in validate() methods.

Spec wire-format compliance (DirectPayment 2.2.1):
  Terminal:   coordinates -> GeoLocation {latitude, longitude}
  FAC:        id (not fac_id), total_costs -> Price {excl_vat, incl_vat},
              currency at root level (separate from total_costs)
"""

from rest_framework import serializers

from generic.validators import validate_latitude, validate_longitude
from ocpi22.payments.models import Terminal, FinancialAdviceConfirmation
from ocpi22.payments.validators import validate_currency_code


class GeoLocationSerializer(serializers.Serializer):
    """
    Validates an incoming GeoLocation object per spec §4.1.
    Used as a nested write-only field on TerminalSerializer.
    Both fields are required together — partial coordinates are rejected by DRF
    before to_internal_value on the parent is reached.
    """

    latitude = serializers.CharField(
        max_length=10,
        validators=[validate_latitude],
    )
    longitude = serializers.CharField(
        max_length=11,
        validators=[validate_longitude],
    )


class PriceSerializer(serializers.Serializer):
    """
    Validates an incoming Price object per spec §5.2.2.
    Note: currency is a separate root-level field in the spec — it is NOT
    part of this nested object on the wire, so it does not appear here.
    Used as a nested write-only field on FinancialAdviceConfirmationSerializer.
    """

    excl_vat = serializers.FloatField()
    incl_vat = serializers.FloatField(required=False, allow_null=True)


class TerminalSerializer(serializers.ModelSerializer):
    """
    Serializer for Terminal — handles both incoming (POST from PTP) and outgoing
    (GET responses) directions.

    Incoming wire format (spec §5.1.1.5, Table 5.6 — CPO side):
        coordinates: {latitude, longitude}  (optional)

    Note: location_ids and evse_uids are NOT accepted on incoming POST.
    Per spec §5.1.1.5: "no location ids should be included as the assignment
    will be done by the CPO." Location assignment is an outbound CPO → PTP
    operation (spec Table 5.1 — PTP side PATCH/PUT).

    Outgoing wire format (spec §5.1.2, §5.1.3):
        coordinates: {latitude, longitude}  (omitted when both are null)
        location_ids: [str, ...]
        evse_uids: [str, ...]
        last_updated: datetime
    """

    coordinates = GeoLocationSerializer(
        required=False, allow_null=True, write_only=True
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
            "last_updated",
        ]

    def to_internal_value(self, data):
        validated_data = super().to_internal_value(data)

        if "coordinates" in validated_data:
            coord_data = validated_data.pop("coordinates")
            if coord_data is not None:
                validated_data["latitude"] = coord_data["latitude"]
                validated_data["longitude"] = coord_data["longitude"]

        return validated_data

    def to_representation(self, instance):
        data = super().to_representation(instance)

        if instance.latitude and instance.longitude:
            data["coordinates"] = {
                "latitude": instance.latitude,
                "longitude": instance.longitude,
            }
        else:
            data.pop("coordinates", None)

        data["location_ids"] = instance.location_ids
        data["evse_uids"] = instance.evse_uids

        return data


class FinancialAdviceConfirmationSerializer(serializers.ModelSerializer):
    """
    Single serializer for FinancialAdviceConfirmation — handles both incoming
    (POST from PTP) and outgoing (GET responses) directions.

    Incoming wire format (spec §5.2.1.3, §5.2.2):
        id:                      str   (maps to fac_id on model)
        total_costs:             {excl_vat, incl_vat?}
        currency:                str   (root-level, separate from total_costs)

    Outgoing wire format (spec §5.2.2, §5.2.3):
        id:                      str
        total_costs:             {excl_vat, incl_vat?}
        currency:                str   (root-level)
    """

    id = serializers.CharField(source="fac_id")
    total_costs = PriceSerializer(required=True, write_only=True)
    currency = serializers.CharField(
        max_length=3,
        validators=[validate_currency_code],
    )

    class Meta:
        model = FinancialAdviceConfirmation
        fields = [
            "id",
            "authorization_reference",
            "total_costs",
            "currency",
            "eft_data",
            "capture_status_code",
            "capture_status_message",
            "last_updated",
        ]

    def to_internal_value(self, data):
        validated_data = super().to_internal_value(data)

        cost_data = validated_data.pop("total_costs")
        validated_data["total_cost_excl_vat"] = cost_data["excl_vat"]
        validated_data["total_cost_incl_vat"] = cost_data.get("incl_vat")

        return validated_data

    def to_representation(self, instance):
        data = super().to_representation(instance)

        total_costs: dict = {"excl_vat": instance.total_cost_excl_vat}
        if instance.total_cost_incl_vat is not None:
            total_costs["incl_vat"] = instance.total_cost_incl_vat
        data["total_costs"] = total_costs

        data["currency"] = instance.currency

        return data
