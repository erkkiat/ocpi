from rest_framework import serializers

from ocpi22.payments.models import Terminal, FinancialAdviceConfirmation


class TerminalBaseSerializer(serializers.ModelSerializer[Terminal]):
    location_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
        help_text="List of Location UIDs this terminal can start sessions on",
    )
    evse_uids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
        help_text="List of EVSE UIDs this terminal can start sessions on",
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
            "latitude",
            "longitude",
            "invoice_base_url",
            "invoice_creator",
            "location_ids",
            "evse_uids",
            "last_updated",
        ]
        read_only_fields = ["last_updated"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["location_ids"] = instance.location_ids
        data["evse_uids"] = instance.evse_uids
        return data


class TerminalWriteSerializer(TerminalBaseSerializer):
    terminal_id = serializers.CharField(required=True)


class TerminalSerializer(TerminalBaseSerializer):
    pass


class FinancialAdviceConfirmationSerializer(
    serializers.ModelSerializer[FinancialAdviceConfirmation]
):
    class Meta:
        model = FinancialAdviceConfirmation
        fields = [
            "fac_id",
            "authorization_reference",
            "total_cost_excl_vat",
            "total_cost_incl_vat",
            "currency",
            "eft_data",
            "capture_status_code",
            "capture_status_message",
            "last_updated",
        ]
        read_only_fields = ["last_updated"]
