from django.conf import settings
from rest_framework import fields, serializers
from rest_framework.exceptions import ValidationError

from ocpi22.choices import AuthorizationEnum
from ocpi22.messages import default_error_messages
from ocpi22.models.location import Location, Evse
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi.serializers import SessionSerializer, StrictEvseUidSerializer, StrictLocationIdSerializer
from ocpi22.serializers import CallbacksSerializer


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
    location_id = StrictLocationIdSerializer(
        source='location',
        help_text='The UID of the location for charging'
    )
    evse_id = StrictEvseUidSerializer(
        source='evse',
        help_text='The identifier of the device which provides electricity to one or more connectors'
    )
    connector_id = serializers.CharField(
        required=False,
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        help_text='The connector number used for charging during this transaction'
    )
    contract_id = serializers.CharField(
        default='N/A',
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        help_text='The contract ID for the EV driver who is charging'
    )

    default_error_messages = default_error_messages


class ReserveSerializer(StartChargingSerializer):
    expiration = serializers.IntegerField(
        min_value=1,
        max_value=settings.MAXIMUM_RESERVATION,
        help_text='The length of this reservation in seconds'
    )
    reservation_id = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        help_text='Reservation id, unique for this reservation. If the Receiver (typically CPO) Point '
                  'already has a reservation that matches this reservationId for that Location '
                  'it will replace the reservation.'
    )


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
                  'status', 'display_status', 'message', 'last_updated']

    total_time = serializers.DecimalField(source='total_time_float', read_only=True, max_digits=8, decimal_places=2)
    display_total_time = serializers.CharField(source='total_time', read_only=True)

    display_start_date = serializers.DateTimeField(source='start_date_time', format="%-d.%-m.%Y", read_only=True)
    display_start_time = serializers.DateTimeField(source='start_date_time', format="%H:%M", read_only=True)
    display_status = serializers.SerializerMethodField()

    def get_display_status(self, session):
        return session.get_status_display()


class MSPCallbacksSerializer(CallbacksSerializer):
    URL = 'authorize_token_url'
    authorize_token_url = serializers.URLField()


class MSPAuthorizeCallbackSerializer(serializers.Serializer):
    token_id = serializers.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH)
