import pprint
from collections import OrderedDict

from rest_framework import serializers

from ocpi22.ocpi_api.serializers import LocationIdSerializer
from ocpi22.models.token import Token
from ocpi22.util import SerializerCleanedUp

pp = pprint.PrettyPrinter(indent=4).pprint


class CommandTokenSerializer(SerializerCleanedUp):
    class Meta:
        fields = ['country_code', 'party_id', 'uid', 'type',
                  'contract_id', 'visual_number', 'issuer', 'group_id',
                  'valid', 'whitelist', 'language', 'default_profile_type', 'last_updated']

    country_code = serializers.CharField(required=True)
    party_id = serializers.CharField(required=True)
    uid = serializers.CharField(required=True)
    type = serializers.ChoiceField(choices=Token.TYPE_CHOICES, required=True)
    contract_id = serializers.CharField(required=True)
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)

    def create(self, validated_data):
        raise NotImplementedError()

    def update(self, instance, validated_data):
        raise NotImplementedError()


class StartSessionSerializer(serializers.Serializer):
    response_url = serializers.URLField(
        help_text='URL that the CommandResult POST should be sent to. '
                  'This URL might contain a unique ID to be able to distinguish between StartSession requests.'
    )
    token = CommandTokenSerializer(
        help_text='Token object the Charge Point has to use to start a new session. '
                  'The Token provided in this request is pre-authorized by the eMSP.'
    )
    location_id = serializers.CharField(
        max_length=36,
        help_text='Location.id of the Location (belonging to the CPO this request was sent to) '
                  'on which a session is to be started.'
    )
    evse_uid = serializers.CharField(
        max_length=36,
        required=False, allow_blank=True,
        help_text='Optional EVSE.uid of the EVSE of this Location on which a session is to be started.'
    )
    authorization_reference = serializers.CharField(
        max_length=36,
        required=False, allow_blank=True,
        help_text='Reference to the authorization given by the eMSP, '
                  'when given, this reference will be provided in the relevant Session and/or CDR.'
    )


class StopSessionSerializer(serializers.Serializer):
    response_url = serializers.URLField(
        help_text='URL that the CommandResult POST should be sent to. '
                  'This URL might contain a unique ID to be able to distinguish between StopSession requests.'
    )
    session_id = serializers.CharField(
        max_length=36,
        help_text='Session.id of the Session that is requested to be stopped.'
    )


class UnlockConnectorSerializer(serializers.Serializer):
    response_url = serializers.URLField(
        help_text='URL that the CommandResult POST should be sent to. '
                  'This URL might contain an unique ID to be able to distinguish between UnlockConnector requests.'
    )
    location_id = LocationIdSerializer(
        max_length=36,
        help_text='Location.id of the Location (belonging to the CPO this request is send to) '
                  'of which it is requested to unlock the connector.'
    )
    evse_uid = serializers.CharField(
        max_length=36,
        required=False, allow_blank=True,
        help_text='EVSE.uid of the EVSE of this Location of which it is requested to unlock the connector.'
    )
    connector_id = serializers.CharField(
        max_length=36,
        help_text='Connector.id of the Connector of this Location of which it is requested to unlock.'
    )


class DisplayTextSerializer(serializers.Serializer):
    # Language Code ISO 639-1.
    language = serializers.CharField(max_length=2)

    # Text to be displayed to a end user. No markup, html etc. allowed.
    text = serializers.CharField(max_length=512)


class CommandResponse(serializers.Serializer):
    NOT_SUPPORTED = 'NOT_SUPPORTED'
    REJECTED = 'REJECTED'
    ACCEPTED = 'ACCEPTED'
    UNKNOWN_SESSION = 'UNKNOWN_SESSION'

    RESULT_OPTIONS = (
        ('NOT_SUPPORTED', 'Not supported'),  # The requested command is not supported by this CPO,
        # Charge Point, EVSE etc.
        ('REJECTED', 'Rejected'),  # Command request rejected by the CPO.
        # (Session might not be from a customer
        # of the eMSP that send this request)
        ('ACCEPTED', 'Accepted'),  # Command request accepted by the CPO.
        ('UNKNOWN_SESSION', 'Session is not valid'),  # The Session in the requested command is not known by this CPO.
    )

    # Response from the CPO on the command request.
    result = serializers.ChoiceField(choices=RESULT_OPTIONS)

    # Timeout for this command in seconds. When the Result is not received within this timeout,
    # the eMSP can assume that the message might never be send.
    timeout = serializers.IntegerField()

    # Human-readable description of the result (if one can be provided), multiple languages can be provided.
    message = serializers.SerializerMethodField()

    @staticmethod
    def get_message(obj):
        return [
            dict(language=o['language'], text=o['text'])
            for o in obj['message']
        ]


class CommandResultBase(serializers.Serializer):
    RESULT_OPTIONS = (
        ('ACCEPTED', 'Accepted'),  # Command request accepted by the Charge Point.
        ('CANCELED_RESERVATION', 'CPO cancelled reservation'),  # The Reservation has been canceled by the CPO.
        ('EVSE_OCCUPIED', 'EVSE is currently in use'),  # EVSE is currently occupied, another session is ongoing
        # Cannot start a new session
        ('EVSE_INOPERATIVE', 'EVSE is inoperative'),  # EVSE is currently inoperative or faulted.
        ('FAILED', 'Command failed'),  # Execution of the command failed at the Charge Point.
        ('NOT_SUPPORTED', 'Command is not supported'),  # The requested command is not supported
        # by this Charge Point, EVSE etc.
        ('REJECTED', 'Command rejected'),  # Command request rejected by the Charge Point.
        ('TIMEOUT', 'Command timeout'),  # Command request timeout, no response received
        # from the Charge Point in a reasonable time.
        ('UNKNOWN_RESERVATION', 'No matching reservation'),  # The Reservation in the requested command
        # is not known by this Charge Point.
    )

    # Result of the command request as sent by the Charge Point to the CPO.
    result = serializers.ChoiceField(choices=RESULT_OPTIONS)


class CpoCommandResult(CommandResultBase):
    token_id = serializers.CharField(
        max_length=36,
        help_text='The token used for the charging session'
    )


class CommandResult(CommandResultBase):
    # Human-readable description of the reason (if one can be provided), multiple languages can be provided.
    message = serializers.SerializerMethodField()

    @staticmethod
    def get_message(obj):
        pp(obj)
        return [
            OrderedDict(language=o['language'], text=o['text'])
            for o in obj['message']
        ]
