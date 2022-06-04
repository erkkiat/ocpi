import logging
import os
from typing import Optional

import redis
from django.conf import settings
from django.utils import timezone
from django.utils.module_loading import import_string
from rest_framework import routers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.reverse import reverse

from ocpi22.choices import OcpiRolesEnum, get_language
from ocpi22.commands.serializers import CpoCommandResultSerializer, CommandResultSerializer
from ocpi22.cpo.serializers import CpoSessionSerializer, \
    StatusChangeSerializer, AuthorizationSerializer, MeterValuesSerializer, StartTransactionSerializer, \
    StopTransactionSerializer, CallbacksSerializer
from ocpi22.cpo.util import get_callbacks_parameter, command_store
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.ocpi.serializers import CdrSerializer
from ocpi22.ocpi.util import generate_session_uid
from ocpi22.routing import find_credentials
from ocpi22.sessions.util import create_session
from ocpi22.tasks import send_ocpi_request
from ocpi22.tokens.auth import authorize_token, TokenAuthorization, get_session_by_adhoc_token
from ocpi22.tokens.util import get_token_id
from ocpi22.logging import log_error
from ocpiconnector import slack_logging

from pprint import PrettyPrinter

from ocpiconnector.ocpi_identities import Party, get_our_party

pp = PrettyPrinter(indent=4).pprint
slack_logging.init()


# class CpoEvseViewSet(mixins.RetrieveModelMixin,
#                      mixins.UpdateModelMixin,
#                      mixins.DestroyModelMixin,
#                      mixins.ListModelMixin,
#                      GenericViewSet):
#     """
#     This is an optimised subset of the EVSE information available in the OCPI Connector.
#     """
#     filter_backends = [DjangoFilterBackend]
#     filterset_fields = ['status']
#     pagination_class = LimitOffsetPagination
#
#     @staticmethod
#     def put(request, evse_id=None):
#         if not evse_id:
#             evse_id = request.data['uid']
#         # noinspection PyUnresolvedReferences
#         evse = Evse.objects.get(uid=evse_id)
#         serializer = EvseSerializer(evse, data=request.data)
#         if serializer.is_valid():
#             serializer.save()
#             send_evse_updates(evse.uid)
#             return Response(serializer.data)
#         else:
#             return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
#
#     @action(methods=['GET', 'PATCH'], detail=False,
#             url_path='(?P<evse_id>[^/.]+)', url_name='by-id')
#     def evse_by_id(self, request, evse_id) -> Response:
#         """
#         This URL is used for sending charger status updates to the Connector using the PATCH method.
#         Status updates should be real time, so that the eMSPs can show the accurate availability to their customers.
#
#         You can try the status update by changing the status
#         in the input box below and clicking the "PATCH" button.
#
#         See OPTIONS for a detailed API schema.
#
#         """
#         evse = get_object_or_404(Evse, uid=evse_id)
#         # Todo: Handle overlapping EVSE UIDs (how to refer to Evse.location.country_code...)
#
#         if request.method == 'GET':
#             serializer = EvseSerializer(evse, context={'request': request})
#             return Response(serializer.data)
#
#         elif request.method == 'PATCH':
#             serializer = EvseSerializer(evse, data=request.data, partial=True, context={'request': request})
#             if serializer.is_valid():
#                 serializer.save()
#                 send_evse_updates(evse.uid)
#                 return Response(serializer.data)
#             else:
#                 return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
#
#         return Response(status=status.HTTP_400_BAD_REQUEST)
#
#     # noinspection PyUnresolvedReferences
#     queryset = Evse.objects.all().order_by('created')
#     serializer_class = EvseSerializer
#     lookup_field = 'evse_id'


# class LocationQuickViewSet(mixins.ListModelMixin,
#                            mixins.UpdateModelMixin,
#                            mixins.RetrieveModelMixin,
#                            GenericViewSet):
#     """
#     This is the endpoint for testing your data format for updating locations.
#     Please note that all IDs should remain constant, since they are referred to by many systems.
#
#     """
#
#     # noinspection PyUnresolvedReferences
#     def put(self, request, uid=None):
#         if uid:
#             our_country_code, our_party_id = Location.get_owner_identity().split('*')
#
#             # Write over an existing Location
#             location: Location = get_object_or_404(Location,
#                                                    uid=uid,
#                                                    country_code=our_country_code,
#                                                    party_id=our_party_id)
#             serializer = self.get_serializer(location, data=request.data)
#         else:
#             # Create a new object
#             # This relies on serializer.create()
#             serializer = self.get_serializer(data=request.data)
#
#         if serializer.is_valid():
#             serializer.save()
#             our_country_code, our_party_id = Location.get_owner_identity().split('*')
#
#             location: Location = get_object_or_404(Location,
#                                                    uid=uid,
#                                                    country_code=our_country_code,
#                                                    party_id=our_party_id)
#             serializer = self.get_serializer(location)
#             ic(serializer.data)
#             return Response(serializer.data)
#         else:
#             return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
#
#     @action(methods=['GET', 'PATCH'], detail=False,
#             url_path='(?P<uid>[^/.]+)')
#     def by_id(self, request, uid) -> Response:
#         # noinspection PyUnresolvedReferences
#         our_country_code, our_party_id = Location.get_owner_identity().split('*')
#
#         location = get_object_or_404(Location, uid=uid,
#                                      country_code=our_country_code,
#                                      party_id=our_party_id)
#
#         if request.method == 'GET':
#             serializer = LocationQuickSerializer(location, context={'request': request})
#             return Response(serializer.data)
#
#         elif request.method == 'PATCH':
#             serializer = LocationQuickSerializer(location, data=request.data, partial=True,
#                                                  context={'request': request})
#             if serializer.is_valid():
#                 serializer.save()
#                 # noinspection PyUnresolvedReferences
#                 serializer = LocationQuickSerializer(Location.objects.get(uid=uid))
#                 return Response(serializer.data)
#             else:
#                 return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
#
#         return Response(status=status.HTTP_400_BAD_REQUEST)
#
#     # noinspection PyUnresolvedReferences
#     queryset = Location.objects.all().order_by('created')
#     serializer_class = LocationQuickSerializer
#     pagination_class = LimitOffsetPagination
#     lookup_field = 'uid'
#
#     @staticmethod
#     def get_object(uid=None) -> Location:
#         # Needed for OPTIONS to work in list view, could just return None
#         if uid:
#             return get_object_or_404(Location, uid=uid)


# Todo: limit access to certain privilege holders
class ChargePointViewSet(viewsets.GenericViewSet):
    """
    The charge point is connected to roaming networks through this API. It interprets the OCPP
    status and other data from the charge point.
    """

    # noinspection PyUnresolvedReferences
    queryset = Location.objects.all()  # Todo: Just in case, show only our Locations
    lookup_field = 'uid'

    def get_serializer_class(self):
        return dict(
            authorize=AuthorizationSerializer,
            status_change=StatusChangeSerializer,
            start_transaction=StartTransactionSerializer,
            meter_values=MeterValuesSerializer,
            stop_transaction=StopTransactionSerializer,
            callbacks=CallbacksSerializer,
            remote_command_result=CpoCommandResultSerializer,
        ).get(self.action_map.get('post'), StatusChangeSerializer)

    @action(methods=('GET', 'POST'), detail=False)
    def status_change(self, request):
        """
        Update the charge point availability to the roaming network parties.

        **IMPORTANT**: To prevent the EV battery from running out , please update the status
        whenever your monitoring notices a possible problem with the charge point. This way
        we will be able to show the real availability status to the driver.

        ## Status codes

        * `HTTP_200_OK` when the EVSE status has been successfully updated
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_404_NOT_FOUND` when the EVSE or Token is not found

        """

        # Todo: Fail if no Tariffs for any Connector in this EVSE

        try:
            if request.method == 'POST':
                serializer = StatusChangeSerializer(data=request.data)
                if serializer.is_valid():
                    ocpp_status = serializer.initial_data.get('status')
                    ocpi_status = serializer.validated_data.get('status')

                    # Todo: Filter just our evses
                    evse: Evse = serializer.validated_data.get('evse')

                    evse.status = ocpi_status
                    evse.last_updated = timezone.now()
                    evse.location.update_last_updated()
                    evse.save()
                    evse.send_status_updates()

                    return Response(
                        dict(
                            status_text=f'EVSE status has been changed',
                            evse=evse.uid,
                            ocpi_status=evse.status,
                            ocpp_status=ocpp_status
                        )
                    )
                else:
                    return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response(dict(help='Please see `OPTIONS` for the schema'), status=status.HTTP_400_BAD_REQUEST)
        except (Evse.DoesNotExist, Token.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)

    @action(methods=('GET', 'POST'), detail=False)
    def authorize(self, request):
        """
        Authorize charging using a specific RFID token. This API call is not mandatory for starting a
        charging session. `Start_transaction` will request authorization from MSP if needed.

        **NOTE**: Authorization responses are cached for 15 minutes, so feel free to
        call this endpoint multiple times when preparing to start a charging session.

        ## Status codes

        * `HTTP_200_OK` when the RFID tag was authorized for charging
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_401_UNAUTHORIZED` when the RFID tag exists, but is not valid for charging at the moment
        * `HTTP_404_NOT_FOUND` when the RFID tag does not exist
        """
        try:
            if request.method == 'POST':
                serializer = AuthorizationSerializer(data=request.data)
                if serializer.is_valid():
                    evse: Evse = serializer.validated_data.get('evse')
                    token: Token = serializer.validated_data.get('token')
                    if isinstance(token, str):
                        # This is an AD_HOC_USER or APP_USER Token
                        authorization: TokenAuthorization = authorize_token(token, evse.location)
                        if authorization:
                            # eMSP has already authorized this AD HOC token for 15 minutes
                            token = AdhocToken(uid=token, valid=True, owner=authorization.party,
                                               type=authorization.token_type)
                    else:
                        authorization: TokenAuthorization = authorize_token(token, evse.location)

                    if not authorization:
                        return Response(
                            dict(
                                status_text='Token is (temporarily) not valid',
                                token_id=get_token_id(token),
                            ),
                            status=status.HTTP_401_UNAUTHORIZED
                        )

                    return Response(
                        dict(
                            allowed=authorization.allowed,
                            status_text=get_language('xx', authorization.info) or
                                        get_language('en', authorization.info) or '',
                            display_text=authorization.info or '',
                            evse_id=evse.uid,
                            token_id=token.uid,
                            token_type=token.type,
                            billed_to=token.party(),
                            authorization_reference=authorization.authorization_reference,
                            authorization_method=authorization.auth_method,
                        ), status=status.HTTP_200_OK if authorization.allowed == Token.ALLOWED
                        else status.HTTP_401_UNAUTHORIZED
                    )
                else:
                    return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response(dict(help='Please see `OPTIONS` for the schema'), status=status.HTTP_400_BAD_REQUEST)
        except (Evse.DoesNotExist, Token.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)

    @action(methods=('GET', 'POST'), detail=False)
    def start_transaction(self, request):
        """
        This call starts the charging transaction (which equals the OCPI session in the roaming network).

        **ENERGY**: If your charge point doesn't reset its energy meter between charging sessions,
        set start_kwh to the current meter value at the start of the session.

        **AUTHORIZATION REQUEST**: You don't have to call the `authorization` endpoint before `start_transaction`,
        since we will call it for you. Also, authorization requests are not sent to MSP when the
        Token has `whitelist=ALWAYS`, and in such cases **authorization_reference will be an empty string**.

        **CHARGER STATUS**: Please update the status to `CHARGING` by using `status_change`.
        The session will be started regardless of charger status,
        in case some status change messages have been lost on the way.

        ## Status codes

        * `HTTP_200_OK` when the charging session was started successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_401_UNAUTHORIZED` when the APP_USER token has expired
        * `HTTP_404_NOT_FOUND` when the Token or the EVSE doesn't exist
        * `HTTP_409_CONFLICT` when a Session with the same internal_reference already exists
        """
        try:
            session: Session = Session.objects.none()

            if request.method == 'POST':
                serializer = StartTransactionSerializer(data=request.data)
                if serializer.is_valid():
                    evse: Evse = serializer.validated_data['evse']
                    connector_id: str = serializer.validated_data['connector_id']
                    internal_reference = serializer.validated_data.get('internal_reference')
                    token = serializer.validated_data['token']
                    start_kwh = serializer.validated_data['start_kwh']

                    if internal_reference and Session.objects.filter(internal_reference=internal_reference).exists():
                        return Response(
                            dict(
                                status_text=f'Session with internal reference `{internal_reference}` already exists',
                            ),
                            status=status.HTTP_409_CONFLICT,
                        )

                    if isinstance(token, Token):
                        party = token.party()
                    else:
                        # AD HOC Token uid, we need to fetch needed info
                        authorization: TokenAuthorization = authorize_token(token)
                        if not authorization:
                            return Response(dict(
                                status_text='Token is (no longer) valid',
                                token_id=get_token_id(token),
                            ), status=status.HTTP_401_UNAUTHORIZED)
                        party = authorization.party
                        session = get_session_by_adhoc_token(token, max_age_minutes=14)
                        session.connector = Connector.get_if_exists(uid=connector_id)
                        session.internal_reference = internal_reference or None
                        session.status = Session.ACTIVE
                        session.save()
                        session.send_updates()
                        logging.info(f'New session {session.uid} active at {evse.evse_id}')

                    if not session:
                        # Todo: Session.currency needs to match with Tariff currency
                        session = create_session(
                            # Todo: Make sure overlapping evse.uid is not a problem for CPO + eMSP role
                            #   Other CPO can have same ID
                            uid=generate_session_uid(), internal_reference=internal_reference,
                            evse_uid=evse, location_id=evse.location, connector_id=connector_id,
                            token_id=get_token_id(token), billed_to=party, start_kwh=start_kwh, stop_kwh=start_kwh,
                            session_status=Session.ACTIVE
                        )
                    session_serializer = CpoSessionSerializer(instance=session)
                    return Response(
                        dict(
                            status_text=f'Session started',
                            session=session_serializer.data,
                        )
                    )
                else:
                    return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response(dict(help='Please see `OPTIONS` for the schema'), status=status.HTTP_400_BAD_REQUEST)
        except (Evse.DoesNotExist, Token.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)

    @action(methods=('GET', 'POST'), detail=False)
    def meter_values(self, request):
        """
        Update the session progress. This endpoint should be called at least once per minute with the
        up to date information about the ongoing charging session.

        ## Status codes

        * `HTTP_200_OK` when the session was updated with the provided meter values
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_403_FORBIDDEN` when the session is not active
        * `HTTP_404_NOT_FOUND` when the session doesn't exist
        * `HTTP_409_CONFLICT` when the applicable Tariff is misconfigured

        ## Energy

        The used energy is calculated by `kwh - start_kwh` (given in `start_transaction`).

        """
        try:
            if request.method == 'POST':
                serializer = MeterValuesSerializer(data=request.data)
                if serializer.is_valid():
                    kwh = serializer.validated_data['kwh']
                    soc = serializer.validated_data.get('soc')
                    power = serializer.validated_data.get('power')
                    if 'session' not in serializer.validated_data \
                            and 'internal_reference' not in serializer.validated_data:
                        raise ValidationError(
                            'Please specify either session_id or internal_reference for the charging transaction'
                        )
                    session = serializer.validated_data.get('session')
                    if not session:
                        internal_reference = serializer.validated_data.get('internal_reference')
                        session = Session.get_if_exists(
                            internal_reference=internal_reference
                        )
                        if not session:
                            raise ValidationError(f'Session with internal reference `{internal_reference}` not found')
                        serializer.validated_data.pop('internal_reference', None)

                    # We found a valid Session
                    if session.status == Session.ACTIVE:
                        session.stop_kwh = kwh
                        session.update_last_updated()
                        session.calculate_price()
                        session.save(update_fields=['stop_kwh', 'total_cost_incl_vat', 'total_cost_excl_vat'])
                        chargingperiods = session.set_charging_period(serializer.validated_data)
                        session.send_updates(chargingperiods)

                        return Response(
                            dict(
                                status_text=f'Session updated',
                                session_id=session.uid,
                                internal_reference=session.internal_reference,
                                start_kwh=session.start_kwh,
                                now_kwh=kwh,
                                total_kwh=session.kwh,
                                power=power,
                                price=session.cost(),
                                soc=soc,
                            )
                        )
                    else:
                        return Response(
                            dict(
                                status_text=f'Updating a finished session is not possible',
                                session_id=session.uid,
                                internal_reference=session.internal_reference,
                                start_kwh=session.start_kwh,
                                now_kwh=kwh,
                                total_kwh=session.kwh,
                                power=power,
                                price=session.cost(),
                                soc=soc,
                            ), status=status.HTTP_403_FORBIDDEN
                        )

                else:
                    return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response(dict(help='Please see `OPTIONS` for the schema'), status=status.HTTP_400_BAD_REQUEST)
        except (Evse.DoesNotExist, Token.DoesNotExist, Session.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)
        except ValidationError as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_409_CONFLICT)

    @action(methods=('GET', 'POST'), detail=False)
    def stop_transaction(self, request):
        """
        End the transaction, charging session has been finished.

        **ENERGY**: The used energy is calculated by `stop_kwh - start_kwh`
        (`start_kwh` was given in `start_transaction`).

        **CHARGER STATUS**: Please update the status by using `status_change`.

        ## Status codes

        * `HTTP_200_OK` when the session was finished and Charge Detail Record was created successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_404_NOT_FOUND` when the Session doesn't exist
        * `HTTP_409_CONFLICT` when the Session has already been finished earlier
        """
        try:
            if request.method == 'POST':
                serializer = StopTransactionSerializer(data=request.data)
                if serializer.is_valid():
                    session = serializer.validated_data.get('session')
                    stop_kwh = serializer.validated_data.get('stop_kwh')
                    if not session:
                        internal_reference = serializer.validated_data.get('internal_reference')
                        session = Session.get_if_exists(internal_reference=internal_reference)
                        if not session:
                            raise ValidationError(f'Session with internal_reference `{internal_reference}` not found.')

                    if session.is_final():
                        return Response(dict(status_text='Session was completed earlier, cannot stop if twice'),
                                        status=status.HTTP_409_CONFLICT)
                    if stop_kwh:
                        session.kwh = stop_kwh
                    session.status = Session.COMPLETED
                    session.calculate_price()
                    session.save(update_fields=['stop_kwh', 'status', 'total_cost_incl_vat', 'total_cost_excl_vat'])
                    session.send_updates()

                    # Create the corresponding CDR (it will also be sent to other party)
                    from ocpi22.models.cdr import Cdr
                    cdr = Cdr.create_based_on_session(session)
                    cdr.save()

                    cdr_json = CdrSerializer(instance=cdr)
                    session_serializer = CpoSessionSerializer(instance=session)

                    return Response(
                        dict(
                            status_text='Session finished',
                            session_id=session.uid,
                            internal_reference=session.internal_reference,
                            kwh_total=session.kwh,
                            session=session_serializer.data,
                            charge_detail_record=cdr_json.data
                        )
                    )
                else:
                    return Response(data=serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # method == GET
            return Response(dict(help='Please see `OPTIONS` for the schema'), status=status.HTTP_400_BAD_REQUEST)
        except (Evse.DoesNotExist, Token.DoesNotExist, Session.DoesNotExist) as e:
            return Response(
                dict(status=str(e)),
                status=status.HTTP_404_NOT_FOUND)

    def _get_callbacks(self):
        serializer = CallbacksSerializer()
        data = dict(
            [(key, get_callbacks_parameter(key)) for key in serializer.fields.keys()]
        )
        serializer = CallbacksSerializer(instance=data)
        return serializer.data

    @action(methods=('GET', 'POST', 'PATCH'), detail=False)
    def callbacks(self, request):
        """
        You need to tell the OCPI Connector where to send commands such as `start transaction` and
        `stop transaction`. Using this endpoint you can set and get your callback URLs and
        user credentials needed for accessing the endpoints you specify.

        > **BASIC AUTHENTICATION**: Include user credentials and port in URL,
        > for example `https://user:password@example.com:1234/path/to/my/endpoint/`.

        ## Status codes

        * `HTTP_200_OK` when the callbacks were set successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way

        """
        try:
            if request.method == 'GET':
                result = self._get_callbacks()
                # Example
                # serializer = CallbacksSerializer()
                # return_values = MyMetadata().get_serializer_info(serializer)
                # result.update(return_values)
                return Response(result)
            if request.method in ('POST', 'PATCH'):
                partial = bool(request.method == 'PATCH')
                serializer = CallbacksSerializer(data=request.data, partial=partial)
                if serializer.is_valid():
                    serializer.save()
                    get_callbacks_parameter.cache_clear()
                    return Response(self._get_callbacks())
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except redis.exceptions.ConnectionError as e:
            logging.error(f'{settings.HOSTNAME}: Cannot read and store callback settings  '
                          f'due to trouble connecting with Redis: {e}')
            return Response(
                dict(
                    status_text='Unable to store settings due to connection problem with Redis. '
                                'This is our fault, sorry. Support has been alerted.'
                ),
                status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(f'{request.method} is not supported', status=status.HTTP_400_BAD_REQUEST)

    @action(methods=('GET', 'POST'), detail=False,
            url_path='remote_command_result(?:/(?P<authorization_reference>[^/.]+))?')
    def remote_command_result(self, request, authorization_reference=None):
        """
        Using this endpoint you tell OCPI Connector if the requested remote command has been successful.
        You'll need the authorization reference in the URL, so you must use the exact response_url you get when
        the OCPI Connector calls your start_transaction callback.


        ## Status codes

        * `HTTP_200_OK` when the call was succesful
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way

        """
        try:
            if request.method == 'GET':
                return Response(dict(help='Please see `OPTIONS` for the schema'), status=status.HTTP_400_BAD_REQUEST)

            command = command_store[authorization_reference]

            if request.method in ('POST'):
                serializer = CpoCommandResultSerializer(data=request.data)
                if serializer.is_valid():
                    token_element = command.get('token') or command.get('ad_hoc_token')
                    token_id = token_element.get('uid') if token_element else ''
                    session = get_session_by_adhoc_token(token_id, max_age_minutes=15)

                    params = dict(
                        result=serializer.validated_data.get('result')
                    )
                    ocpi_serializer = CommandResultSerializer(instance=params)
                    response_url = command.get('response_url')
                    to = Party(*session.billed_to.split('*'))
                    credentials = find_credentials(to)
                    sender = get_our_party(OcpiRolesEnum.CPO)

                    response = send_ocpi_request(
                        ocpi_serializer.data,
                        response_url,
                        credentials.theirs_base64(),
                        to_country_code=to.country_code,
                        to_party_id=to.party_id,
                        from_country_code=sender.country_code,
                        from_party_id=sender.party_id,
                        method='post',
                        credentials_id=credentials.pk,
                    )
                    return Response(
                        dict(
                            status_text=f'Response received from eMSP',
                            token_id=token_id,
                            authorization_reference=command['authorization_reference'],
                            data=response.get("json"),
                        ), status=response.get('status_code')
                    )
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except redis.exceptions.ConnectionError as e:
            logging.error(f'{settings.HOSTNAME}: Cannot read and store callback settings  '
                          f'due to trouble connecting with Redis: {e}')
            return Response(
                dict(
                    status_text='Unable to store settings due to connection problem. '
                                'This is our fault, sorry. Support has been alerted.'
                ),
                status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except KeyError as e:
            log_error(request, str(e))
            return Response(
                dict(
                    status_text=f'Unable to find eMSP remote command from cache, '
                                f'either the command ID (in URL) is incorrect or '
                                f'the command was issued by eMSP too long ago '
                                f'(expiration is set to {settings.REMOTE_COMMAND_EXPIRATION})'
                ),
                status=status.HTTP_404_NOT_FOUND)

        return Response(f'{request.method} is not supported', status=status.HTTP_400_BAD_REQUEST)

    def get_view_name(self):
        if self.name:
            return f'{self.name.capitalize()}'
        return f'Status Change'

    @staticmethod
    def get_object(uid=None) -> None:
        # Needed for OPTIONS to work in list view
        return None


class ChargePointOperatorAPIView(routers.APIRootView):
    """
    This API is not a part of the OCPI protocol. It is intended as fast shortcut to OCPI roaming.

    > Here you can use the CPO API interfaces intearactively
    > to support your development and integration work.
    > These streamlined interfaces provide the necessary tools for quickly but comprehensively connecting
    > a CPO backend to eMSPs and hubs using the OCPI protocol.

    **ADMIN UI**: All the objects in the OCPI Connector are available for browsing
    and selective modification in the admin tools.
    It also provides tools for maintaining users, groups and their access to the OCPI Connector.

    For more details, click the links below and you will find the step-by-step technical documentation.

    """

    # noinspection PyUnresolvedReferences
    def get(self, request, *args, **kwargs):
        """
        Compile the example URLs for the root page
        """

        result = dict(
            status_management=dict(
                status_change=request.build_absolute_uri(
                    reverse('chargepoint-status-change')
                )
            ),
            charging_session=dict(
                authorize=request.build_absolute_uri(
                    reverse('chargepoint-authorize')
                ),
                start_transaction=request.build_absolute_uri(
                    reverse('chargepoint-start-transaction')
                ),
                meter_values=request.build_absolute_uri(
                    reverse('chargepoint-meter-values')
                ),
                stop_transaction=request.build_absolute_uri(
                    reverse('chargepoint-stop-transaction')
                ),
            ),
            remote_commands=dict(
                callbacks=request.build_absolute_uri(
                    reverse('chargepoint-callbacks')
                ),
                remote_command_result=request.build_absolute_uri(
                    reverse('chargepoint-remote-command-result')
                ),
            ),
        )
        return Response(result)

    def get_view_name(self):
        return 'Charge Point Operator API'


class CPORouter(routers.DefaultRouter):
    APIRootView = ChargePointOperatorAPIView
    root_view_name = 'cpo-api'


class Charger:
    AUTHORIZATION_CHOICES = (
        ('Accepted', 'Accepted'),
        ('Blocked', 'Blocked'),
        ('Expired', 'Expired'),
        ('Invalid', 'Invalid'),
        ('ConcurrentTx', 'ConcurrentTx'),
    )

    class UnlockStatus:
        value = None

        def __int__(self, value):
            assert value in ('Unlocked', 'UnlockFailed', 'NotSupported')
            self.value = value

        def __str__(self):
            return self.value

    @staticmethod
    def remote_start_transaction(token: str, evse: Evse) -> Optional[str]:
        """
        Start a charging session

        @param session:
        @return: Connector ID
        """
        # ic()
        # ic(token, evse)
        # noinspection PyUnresolvedReferences
        connectors = evse.connectors.all()
        if connectors.count(): return connectors[0]
        return None

    @staticmethod
    def remote_stop_transaction(session: Session) -> bool:
        # ic()
        # ic(session)
        return True

    @staticmethod
    def unlock_connector(location_id, evse_uid, connector_id, **kwargs) -> bool:
        # ic()
        # ic(location_id, evse_uid, connector_id, kwargs)
        return True

    @staticmethod
    def add_or_update_token(id_token: str, validity: bool, created=None) -> bool:
        """
        Send a new or changed token to charge point

        @param id_token: Token UID
        @param validity: Is the token valid for use or not
        @return: True, if the token was updated
        """
        # ic()
        # ic(id_token, validity, created)
        return True


charger_class = os.environ.get('CHARGER_CLASS', 'ocpi22.cpo.api.Charger')
CHARGER = import_string(charger_class)
