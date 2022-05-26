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


class StrictTokenIdSerializer(fields.CharField):
    # Return the Token object or pass through the token ID if it's an ADHOC token
    def to_internal_value(self, data):
        token = Token.get_if_exists(uid=data)
        if not token:
            raise ValidationError(f'Token with UID {data} not found')
        return token


class SessionIdSerializer(fields.CharField):
    # Return the Session object or pass through the session ID if unknown
    def to_internal_value(self, data):
        session = Session.get_if_exists(uid=data) or data
        return session


class StrictSessionIdSerializer(fields.CharField):
    # Return the Session object or pass through the session ID if unknown
    def to_internal_value(self, data):
        session = Session.get_if_exists(uid=data)
        if not session:
            raise ValidationError(f'Session with UID {data} not found')
        return session


class StartChargingSerializer(serializers.Serializer):
    location_id = serializers.CharField(
        max_length=36,
        help_text='The UID of the location for charging'
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
    session_id = StrictSessionIdSerializer(
        required=False,
        source='session',
        help_text='The session_id provided by CPO'
    )


class SessionStatusSerializer(serializers.Serializer):
    session_id = StrictSessionIdSerializer(
        required=False,
        source='session',
        help_text='The session_id provided by CPO'
    )
