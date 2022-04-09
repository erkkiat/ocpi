from rest_framework import fields, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.settings import api_settings

from ocpi22.messages import default_error_messages
from ocpi22.models.location import Location, Evse
from ocpi22.models.session import Session
from ocpi22.models.token import Token


class TokenIdSerializer(fields.CharField):
    # Return the Token object or pass through the token ID if it's an ADHOC token
    def to_internal_value(self, data):
        token = Token.get_if_exists(uid=data) or data
        return token


class SessionIdSerializer(fields.CharField):
    # Return the Session object or pass through the session ID if unknown
    def to_internal_value(self, data):
        session = Session.get_if_exists(uid=data)
        if not session:
            return ValidationError(f'Session ID {data} is unknown')
        return session


class StartChargingSerializer(serializers.Serializer):
    location_id = serializers.CharField(
        # source="*",
        max_length=36
    )
    evse_id = serializers.CharField(
        # source='*',
        help_text='The identifier of the device which provides electricity to one or more connectors'
    )
    connector_id = serializers.CharField(
        required=False,
        max_length=36,
        help_text='The connector number used for charging during this transaction'
    )
    contract_id = serializers.CharField(
        default='N/A',
        max_length=36,
        help_text='The contract ID for the EV driver who is charging'
    )
    token_id = TokenIdSerializer(
        source='token',
        help_text='The hidden ID of the RFID token, separate from the visual one'
    )

    default_error_messages = default_error_messages

    def to_internal_value(self, data):
        evse_id = self.initial_data.get('evse_id')
        location_id = self.initial_data.get('location_id')
        location = Location.get_if_exists(uid=location_id, raise_exception=True)
        evse = Evse.get_if_exists(uid=evse_id, location=location, raise_exception=True)
        data = super().to_internal_value(data)
        data['evse'] = evse
        return data


class StopChargingSerializer(serializers.Serializer):
    token_id = TokenIdSerializer(
        required=False,
        source='token',
        help_text='The hidden ID of the RFID token, separate from the visual one'
    )
    session_id = SessionIdSerializer(
        required=False,
        source='session',
        help_text='The session_id provided by ...'
    )

    def validate(self, attrs):
        token = self.initial_data.get('token_id')
        session = self.initial_data.get('session_id')
        if not token and not session:
            raise ValidationError(
                {api_settings.NON_FIELD_ERRORS_KEY: [f'Either token_id or session_id needs to be specified']}
            )
        attrs = super().validate(attrs)
        return attrs
