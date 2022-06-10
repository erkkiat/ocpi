from rest_framework import fields, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.settings import api_settings

from ocpi22.messages import default_error_messages
from ocpi22.models.location import Location, Evse
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi.serializers import SessionSerializer


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
        help_text='The optional session_id provided by CPO'
    )


class SessionStatusSerializer(serializers.Serializer):
    session_id = StrictSessionIdSerializer(
        required=False,
        source='session',
        help_text='The optional session_id provided by CPO'
    )


class MspSessionSerializer(SessionSerializer):
    class Meta:
        model = Session
        fields = ['detail_url', 'country_code', 'party_id', 'uid',
                  'start_date_time', 'end_date_time', 'display_start_date', 'display_start_time',
                  'kwh', 'charging_periods', 'total_time', 'display_total_time',
                  'cdr_token', 'auth_method', 'authorization_reference',
                  'location_id', 'evse_uid', 'connector_id', 'meter_id', 'currency', 'total_cost',
                  'status', 'message', 'last_updated']

    total_time = serializers.DecimalField(source='total_time_float', read_only=True, max_digits=8, decimal_places=2)
    display_total_time = serializers.CharField(source='total_time', read_only=True)

    display_start_date = serializers.DateTimeField(source='start_date_time', format="%-d.%-m.%Y", read_only=True)
    display_start_time = serializers.DateTimeField(source='start_date_time', format="%H:%M", read_only=True)
