import pprint

from django.conf import settings
from django.db.models import TextChoices
from rest_framework import serializers

from ocpi22 import choices
from ocpi22.ocpi.serializers import LocationIdDictSerializer, StrictEvseUidSerializer
from ocpi22.serializers.util import SerializerCleanedUp, UTCDateTimeField
from ocpi22.util import CiStringChoiceField

pp = pprint.PrettyPrinter(indent=4).pprint


class MessageSerializer(serializers.Serializer):
    language = serializers.CharField(max_length=2)
    text = serializers.CharField(max_length=512)


class CommandTokenSerializer(SerializerCleanedUp):
    class Meta:
        fields = [
            "country_code",
            "party_id",
            "uid",
            "type",
            "contract_id",
            "visual_number",
            "issuer",
            "group_id",
            "valid",
            "whitelist",
            "language",
            "default_profile_type",
            "last_updated",
        ]

    uid = serializers.CharField(required=True)
    country_code = serializers.CharField(max_length=2, required=True)
    party_id = serializers.CharField(max_length=3, required=True)

    type = CiStringChoiceField(choices=choices.TOKEN_TYPE_CHOICES, required=True)
    contract_id = serializers.CharField(required=True)
    last_updated = UTCDateTimeField(required=False)

    def create(self, validated_data):
        raise NotImplementedError()

    def update(self, instance, validated_data):
        raise NotImplementedError()


class StartSessionSerializer(serializers.Serializer):
    response_url = serializers.URLField(
        help_text="URL that the CommandResult POST should be sent to. "
        "This URL might contain a unique ID to be able to distinguish between StartSession requests."
    )
    token = CommandTokenSerializer(
        help_text="Token object the Charge Point has to use to start a new session. "
        "The Token provided in this request is pre-authorized by the eMSP."
    )
    location_id = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        help_text="Location.id of the Location (belonging to the CPO this request was sent to) "
        "on which a session is to be started.",
    )
    evse_uid = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        required=False,
        allow_blank=True,
        help_text="Optional EVSE.uid of the EVSE of this Location on which a session is to be started.",
    )
    connector_id = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        required=False,
        allow_blank=True,
        help_text="Optional Connector.id of the Connector of the EVSE on which a session is to be started. "
        "This field is required when the capability: START_SESSION_CONNECTOR_REQUIRED is set on the EVSE.",
    )
    authorization_reference = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        required=False,
        allow_blank=True,
        help_text="Optional reference to the authorization given by the eMSP, "
        "when given, this reference will be provided in the relevant Session and/or CDR.",
    )


class ReserveNowSerializer(serializers.Serializer):
    response_url = serializers.URLField(
        help_text="URL that the CommandResult POST should be sent to. "
        "This URL might contain a unique ID to be able to distinguish between ReserveNow requests."
    )
    token = CommandTokenSerializer(
        help_text="Token object the Charge Point has to use to start a new session. "
        "The Token provided in this request is pre-authorized by the eMSP."
    )
    location_id = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        help_text="Location.id of the Location (belonging to the CPO this request was sent to) "
        "on which a session is to be started.",
    )
    evse_uid = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        required=False,
        allow_blank=True,
        help_text="Optional EVSE.uid of the EVSE of this Location on which a session is to be started.",
    )
    expiry_date = UTCDateTimeField(
        help_text="The Date/Time when this reservation ends, in UTC."
    )
    reservation_id = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        help_text="Reservation id, unique for this reservation. "
        "If the Receiver (typically CPO) Point already has a reservation "
        "that matches this reservationId for that Location it will replace the reservation.",
    )
    authorization_reference = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        required=False,
        allow_blank=True,
        help_text="Optional reference to the authorization given by the eMSP, "
        "when given, this reference will be provided in the relevant Session and/or CDR.",
    )


class StopSessionSerializer(serializers.Serializer):
    response_url = serializers.URLField(
        help_text="URL that the CommandResult POST should be sent to. "
        "This URL might contain a unique ID to be able to distinguish between StopSession requests."
    )
    session_id = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        help_text="Session.id of the Session that is requested to be stopped.",
    )


class UnlockConnectorSerializer(serializers.Serializer):
    response_url = serializers.URLField(
        help_text="URL that the CommandResult POST should be sent to. "
        "This URL might contain an unique ID to be able to distinguish between UnlockConnector requests."
    )
    location_id = LocationIdDictSerializer(
        help_text="Location.id of the Location (belonging to the CPO this request is send to) "
        "of which it is requested to unlock the connector."
    )
    evse_uid = StrictEvseUidSerializer(
        required=False,
        allow_blank=True,
        help_text="Optional EVSE.uid of the EVSE of this Location of which it is requested to unlock the connector.",
    )
    connector_id = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        help_text="Connector.id of the Connector of this Location of which it is requested to unlock.",
    )


class CommandResponse(serializers.Serializer):
    NOT_SUPPORTED = "NOT_SUPPORTED"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"
    UNKNOWN_SESSION = "UNKNOWN_SESSION"

    RESULT_OPTIONS = (
        (
            "NOT_SUPPORTED",
            "Not supported",
        ),  # The requested command is not supported by this CPO,
        # Charge Point, EVSE etc.
        ("REJECTED", "Rejected"),  # Command request rejected by the CPO.
        # (Session might not be from a customer
        # of the eMSP that send this request)
        ("ACCEPTED", "Accepted"),  # Command request accepted by the CPO.
        (
            "UNKNOWN_SESSION",
            "Session is not valid",
        ),  # The Session in the requested command is not known by this CPO.
    )

    # Response from the CPO on the command request.
    result = serializers.ChoiceField(choices=RESULT_OPTIONS)

    # Timeout for this command in seconds. When the Result is not received within this timeout,
    # the eMSP can assume that the message might never be send.
    timeout = serializers.IntegerField()

    # Human-readable description of the result (if one can be provided), multiple languages can be provided.
    message = MessageSerializer(many=True, required=False)


class CommandResultType(TextChoices):
    ACCEPTED = "ACCEPTED", "Accepted"
    CANCELED_RESERVATION = "CANCELED_RESERVATION", "CPO cancelled reservation"
    EVSE_OCCUPIED = "EVSE_OCCUPIED", "EVSE is currently in use"
    EVSE_INOPERATIVE = "EVSE_INOPERATIVE", "EVSE is inoperative"
    FAILED = "FAILED", "Command failed"
    NOT_SUPPORTED = "NOT_SUPPORTED", "Command is not supported"
    REJECTED = "REJECTED", "Command rejected"
    TIMEOUT = "TIMEOUT", "Command timeout"
    UNKNOWN_RESERVATION = "UNKNOWN_RESERVATION", "No matching reservation"


class CommandResultBaseSerializer(serializers.Serializer):
    ACCEPTED = CommandResultType.ACCEPTED.value
    CANCELED_RESERVATION = CommandResultType.CANCELED_RESERVATION.value
    EVSE_OCCUPIED = CommandResultType.EVSE_OCCUPIED.value
    EVSE_INOPERATIVE = CommandResultType.EVSE_INOPERATIVE.value
    FAILED = CommandResultType.FAILED.value
    NOT_SUPPORTED = CommandResultType.NOT_SUPPORTED.value
    REJECTED = CommandResultType.REJECTED.value
    TIMEOUT = CommandResultType.TIMEOUT.value
    UNKNOWN_RESERVATION = CommandResultType.UNKNOWN_RESERVATION.value

    RESULT_OPTIONS = CommandResultType.choices

    # Result of the command request as sent by the Charge Point to the CPO.
    result = serializers.ChoiceField(choices=RESULT_OPTIONS)


class CpoCommandResultSerializer(CommandResultBaseSerializer):
    pass


class CommandResultSerializer(CommandResultBaseSerializer):
    message = MessageSerializer(many=True, required=False)
