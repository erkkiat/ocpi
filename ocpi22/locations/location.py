import requests
from rest_framework.exceptions import ValidationError

import ocpi22.logging as logging

from django.core.validators import RegexValidator
from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.viewsets import GenericViewSet
from rest_framework.generics import get_object_or_404

from ocpi22.locations.serializers import EvseSaveSerializer, EvseSerializer, LocationSerializer, LocationSaveSerializer
from ocpi22.models.location import Location, Evse
from ocpi22.msp.serializers import MSPChargePointStatusCallbackSerializer
from ocpi22.serializers import CallbacksSerializer
from ocpi22.util import matching_operator, OnlyRawBrowsableAPIRenderer, get_callbacks_parameter, build_callback_request
from ocpi22.ocpi.util import NotOwner, OCPIResponse, Ocpi, OCPIPaginationAndHeaders

# Todo: Fetch all Locations for reliable data update, but fetch Tariffs first, since Location refers to them
# Todo: PATCH & PUT Connector
# Todo: DELETE Tariff


evse_validator = RegexValidator(r'[A-Z]{2}\*[A-Za-z0-9]{3}\*[E][A-Za-z0-9][A-Za-z0-9\*]{0,30}$',
                                message='OCPI evse_id has to contain a valid eMI3 EVSE-ID (NL*EVN*E123456ABCD)')


class EvseViewSet(mixins.RetrieveModelMixin,
                  mixins.ListModelMixin,
                  GenericViewSet):
    queryset = Evse.objects.all().order_by('created')
    serializer_class = EvseSerializer
    pagination_class = OCPIPaginationAndHeaders

    @action(methods=['GET', 'PATCH', 'PUT'], detail=False, url_name='by-id',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)/(?P<evse_id>[^/.]+)')
    def evse_by_id(self, request, country_code, party_id, uid, evse_id) -> OCPIResponse:
        evse = get_object_or_404(Evse, uid=evse_id)
        location = evse.location
        if location.uid != uid or location.party_id != party_id or location.country_code != country_code:
            return OCPIResponse(
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                status_message='The EVSE is not owned by the specified party or is not in the specified country')

        if request.method == 'GET':
            serializer = EvseSerializer(evse, context={'request': request})
            return OCPIResponse(serializer.data)

        elif request.method in ('PATCH', 'PUT'):
            data = request.data
            readonly_fields = ('uid', 'evse_id')
            # Remove readonly fields from the incoming data
            for f in readonly_fields:
                data.pop(f, None)

            partial = bool(request.method == 'PATCH')

            serializer = EvseSerializer(evse, data=data, partial=partial, context={'request': request})
            if serializer.is_valid():
                serializer.save()
                return OCPIResponse(serializer.data)
            else:
                return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST,
                                    status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

        return OCPIResponse(http_status=status.HTTP_400_BAD_REQUEST,
                            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)


def send_to_webhook(data, serializer, outbound_serializer=None, timeout=5) -> dict:
    assert issubclass(serializer, CallbacksSerializer), \
        'The serializer needs to be inherited from CallbacksSerializer'
    try:
        OutboundSerializer = outbound_serializer or serializer.OutboundSerializer
        outbound_serializer = OutboundSerializer(data=data)
        assert outbound_serializer.is_valid(), outbound_serializer.errors

        url, kwargs_update = build_callback_request(serializer.URL, data)

        if url:
            kwargs = {}
            headers = {'content-type': 'application/json'}
            kwargs.update(kwargs_update)

            logging.info(f'Calling webhook at url {url}')

            response = requests.post(
                url=url,
                json=outbound_serializer.data,
                headers=headers,
                verify=False,
                timeout=timeout,
                **kwargs)
            if hasattr(serializer, 'ResponseSerializer'):
                data = response.json()
                response_serializer = serializer.ResponseSerializer(data=data)
                if response_serializer.is_valid():
                    return data
                else:
                    logging.error(f'Got a malformed response from webhook at {url}: {data}')
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, ValueError, ValidationError) as e:
        logging.error(f'Problem communicating with webhook {serializer.__class__}: {e}')
    return {}


class LocationViewSet(mixins.ListModelMixin,
                      GenericViewSet):
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['country_code', 'party_id', 'parking_type', 'city', 'publish', 'facilities', 'country']
    pagination_class = OCPIPaginationAndHeaders
    root_view_name = 'locations'
    renderer_classes = [JSONRenderer, OnlyRawBrowsableAPIRenderer]

    lookup_field = "uid"

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'Location {self.kwargs.get("uid")}'
        if self.name:
            return f'{self.name.capitalize()}'
        return 'Locations'

    @staticmethod
    def get_object(uid=None) -> Location:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Location, uid=uid)

    @transaction.atomic
    @action(methods=['GET', 'PATCH', 'PUT'], detail=False, url_name='by-evse-id',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)/(?P<evse_id>[^/.]+)')
    def by_evse_id(self, request, country_code, party_id, uid, evse_id) -> OCPIResponse:
        evse: Evse = get_object_or_404(Evse, uid=evse_id, location__uid=uid)
        location: Location = evse.location

        if location.party_id != party_id or location.country_code != country_code:
            return OCPIResponse(
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                status_message='The EVSE is not owned by the specified party or is not in the specified country')

        if request.method == 'GET':
            serializer = EvseSerializer(evse, context={'request': request})
            return OCPIResponse(serializer.data)

        elif request.method in ('PATCH', 'PUT'):
            data = request.data
            readonly_fields = ['evse_id']
            # Remove readonly fields from the incoming data
            for f in readonly_fields:
                data.pop(f, None)

            data.update(dict(uid=evse_id, country_code=country_code, party_id=party_id))

            partial = request.method == 'PATCH'

            serializer = EvseSaveSerializer(evse, data=data, partial=partial, context={'request': request})
            if serializer.is_valid():
                serializer.save()
                data = {
                    'location_id': evse.location.uid,
                    'evse_id': evse.uid,
                    'status': evse.status
                }
                send_to_webhook(data, MSPChargePointStatusCallbackSerializer)
                return OCPIResponse(serializer.data)
            else:
                return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST,
                                    status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

        return OCPIResponse(http_status=status.HTTP_400_BAD_REQUEST,
                            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    @staticmethod
    @transaction.atomic
    def put(request, data=None, **_kwargs):
        data = data or request.data.get('data', request.data)
        # print(data)
        uid = data.get('id')
        country_code = data.get('country_code')
        party_id = data.get('party_id')

        if request and not matching_operator(request, country_code, party_id):
            return NotOwner()

        if uid:
            location: Location = Location.get_if_exists(uid=uid, country_code=country_code, party_id=party_id)
            if location and location.is_ours():
                return OCPIResponse(f'Location {location} is owned by us and cannot be updated from outside.',
                                    http_status=status.HTTP_401_UNAUTHORIZED,
                                    status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)
            serializer = LocationSaveSerializer(location, data=data)
            if serializer.is_valid():
                logging.info(f'Creating or updating Location {country_code}*{party_id} - {uid}.')
                serializer.save()
                Location.send_hub_updates(serializer.data)
                http_status = status.HTTP_200_OK if location else status.HTTP_201_CREATED
                return OCPIResponse(serializer.data, http_status=http_status)
            else:
                return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST,
                                    status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)
        else:
            return OCPIResponse(
                status_message=f'Country code, party_id and id are required when doing a PUT for a Location.',
                http_status=status.HTTP_400_BAD_REQUEST,
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    # @action(methods=['GET', 'PATCH'], detail=False,
    #         url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)/(?P<evse_uid>[^/.]+)')
    # def by_evse_id(self, request: Request, country_code, party_id, uid, evse_uid, partial=True) -> OCPIResponse:
    #     if request.method != 'GET' and not hasattr(request, 'credentials'):
    #         return OCPIResponse('Credentials are needed for creating Locations.',
    #                             status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
    #                             http_status=status.HTTP_401_UNAUTHORIZED)
    #     location = get_object_or_404(Location, uid=uid, party_id=party_id, country_code=country_code)
    #     evse = get_object_or_404(Evse, uid=evse_uid, location=location)
    #     if request.method == 'PATCH':
    #         print(f'*** Updating Evse {evse_uid} with new status {request.data.get("status")} '
    #               f'from {request.credentials.party()}')
    #         serializer = EvseSerializer(instance=evse, data=request.data, partial=partial)
    #         if serializer.is_valid():
    #             serializer.save()
    #         else:
    #             return OCPIResponse(serializer.errors, http_status=status.HTTP_400_BAD_REQUEST,
    #                                 status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)
    #     else:
    #         serializer = EvseSerializer(instance=evse)
    #     return OCPIResponse(serializer.data)

    @transaction.atomic
    @action(methods=['GET', 'PUT', 'PATCH'], detail=False, url_name='by-id',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def location_by_id(self, request: Request, country_code, party_id, uid) -> OCPIResponse:
        # noinspection PyUnresolvedReferences
        location = get_object_or_404(Location,
                                     country_code=country_code,
                                     party_id=party_id,
                                     uid=uid)
        serializer = LocationSerializer(location, context={'request': request})
        if request.method == 'GET':
            return OCPIResponse(serializer.data)

        elif request.method in ('PUT', 'PATCH'):
            partial = request.method == 'PATCH'

            serializer = LocationSaveSerializer(location,
                                                data=request.data.get('data', request.data),
                                                partial=partial,
                                                context={'request': request})
            if serializer.is_valid():
                serializer.save()
                return OCPIResponse(serializer.data)
            else:
                return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST,
                                    status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

        return OCPIResponse(http_status=status.HTTP_400_BAD_REQUEST,
                            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    # noinspection PyUnresolvedReferences
    queryset = Location.objects.all().order_by('created')
    serializer_class = LocationSerializer
