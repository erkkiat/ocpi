from django.conf import settings
from rest_framework import fields, serializers
from rest_framework.exceptions import ValidationError

from ocpi22.choices import AuthorizationEnum
from util import default_error_messages
from ocpi22.models.location import Evse
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi.serializers import SessionSerializer, StrictEvseUidSerializer, StrictLocationIdSerializer, \
    LocationIdSerializer
from ocpi22.serializers.util import CallbacksSerializer


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


# class SessionIdSerializer(fields.CharField):
#     # Return the Session object or pass through the session ID if unknown
#     def to_internal_value(self, data):
#         session = Session.get_if_exists(uid=data) or data
#         return session


class StrictSessionIdSerializer(fields.CharField):
    # Return the Session object or pass through the session ID if unknown
    def to_internal_value(self, data):
        session = Session.get_if_exists(uid=data)
        if not session:
            raise ValidationError(f'Session with ID {data} not found')
        return session


class StartChargingSerializer(serializers.Serializer):
    location_id = StrictLocationIdSerializer(
        source='location',
        help_text='The UID of the location for charging'
    )
    evse_uid = StrictEvseUidSerializer(
        source='evse',
        help_text='The identifier of the device which provides electricity to one or more connectors'
    )
    token_id = serializers.CharField(
        required=False, max_length=settings.OCPI_22_MAX_UID_LENGTH,
        help_text='The optional identifier of the token that is used for this session. '
                  'NOTE: Use this field if you have your own user database. '
                  'Make sure the account you use for authentication has '
                  'the "ocpi22.charge_with_any_token" permission set or is an admin account.',
    )
    connector_id = serializers.CharField(
        required=False, allow_blank=True, allow_null=True,  # Not supported in OCPI 2.2
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        help_text='The connector number used for charging during this transaction'
    )
    contract_id = serializers.CharField(
        default='N/A',
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        help_text='The contract ID for the EV driver who is charging'
    )
    internal_reference = serializers.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        help_text='Optional session ID from the MSP platform or order number from the MSP billing system',
        required=False, allow_null=True
    )
    max_price = serializers.DecimalField(
        max_digits=6, decimal_places=2, required=False,
        help_text='Optional maximum price for the Session (the amount of money reserved from the debit/credit card)'
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
    token_id = serializers.CharField(
        required=False, max_length=settings.OCPI_22_MAX_UID_LENGTH,
        help_text='The optional identifier of the token that was used for this session. '
                  'Specify this if you are using your own user database.'
    )


class SessionStatusSerializer(serializers.Serializer):
    session_id = StrictSessionIdSerializer(
        required=False,
        source='session',
        help_text='The optional session_id provided by CPO'
    )
    token_id = serializers.CharField(
        required=False, max_length=settings.OCPI_22_MAX_UID_LENGTH,
        help_text='The optional identifier of the token that is used for this session'
    )


class MspSessionSerializer(SessionSerializer):
    class Meta:
        model = Session
        fields = ['detail_url', 'country_code', 'party_id', 'uid',
                  'start_date_time', 'end_date_time',
                  'kwh', 'charging_periods', 'total_time', 'display_total_time',
                  'cdr_token', 'auth_method', 'authorization_reference',
                  'location_id', 'evse_uid', 'connector_id', 'meter_id', 'currency', 'total_cost',
                  'status', 'display_status', 'message', 'last_updated']

    country_code = serializers.CharField(source='ocpi_master.country_code', read_only=True)
    party_id = serializers.CharField(source='ocpi_master.party_id', read_only=True)

    total_time = serializers.DecimalField(source='total_time_float', read_only=True, max_digits=8, decimal_places=2)
    display_total_time = serializers.CharField(source='total_time', read_only=True)

    display_status = serializers.SerializerMethodField()

    @staticmethod
    def get_display_status(session):
        return session.get_status_display()


class MSPAuthorizeCallbackSerializer(CallbacksSerializer):
    URL = 'authorize_token_url'
    authorize_token_url = serializers.URLField()

    class OutboundSerializer(serializers.Serializer):
        token_id = serializers.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH)
        location_id = serializers.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH, required=False, allow_null=True)

    class ResponseSerializer(serializers.Serializer):
        result = serializers.ChoiceField(choices=AuthorizationEnum.choices)
        max_price = serializers.DecimalField(max_digits=6, decimal_places=2, required=False,
                                             help_text='Optional maximum price for the Session')


class MSPChargePointStatusCallbackSerializer(CallbacksSerializer):
    URL = 'chargepoint_status_url'
    chargepoint_status_url = serializers.URLField()

    class OutboundSerializer(serializers.Serializer):
        def __init__(self, data, *args, **kwargs):
            # if isinstance(data, Evse):
            #     data = dict(location_id=data.location.uid, evse_id=data.uid, status=data.status)
            assert isinstance(data, dict), f'Data needs to be a dict for {self.__class__.__name__}'
            assert all(data.values()), f'All values in {self.__class__.__name__} need to be set: {data}'
            super().__init__(data=data, *args, **kwargs)

        location_id = LocationIdSerializer(
            help_text='The Location UID of the EVSE which had a status update'
        )
        evse_id = serializers.CharField(
            help_text='The UID of the EVSE with the changed status'
        )
        status = serializers.ChoiceField(
            choices=Evse.STATUS_CHOICES,
            help_text='The new status of the EVSE'
        )


class MSPSessionCallbackSerializer(CallbacksSerializer):
    URL = 'session_url'  # This needs to match the name of the below element
    session_url = serializers.URLField()

    OutboundSerializer = MspSessionSerializer
