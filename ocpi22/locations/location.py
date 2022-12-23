import ocpi22.logging as logging

from django.core.validators import RegexValidator
from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.viewsets import GenericViewSet
from rest_framework.generics import get_object_or_404

from ocpi22.locations.serializers import EvseSerializer, LocationSerializer, LocationSerializer221
from ocpi22.messages import messages
from ocpi22.models.location import Location, Evse
from ocpi22.msp.serializers import MSPChargePointStatusCallbackSerializer
from ocpi22.rendering import RENDERERS
from ocpi22.util import matching_operator, OCPIVersioning
from ocpi22.ocpi.util import NotOwner, OCPIResponse, Ocpi, OCPIPaginationAndHeaders

# Todo: Fetch all Locations for reliable data update, but fetch Tariffs first, since Location refers to them
# Todo: PATCH & PUT Connector
# Todo: DELETE Tariff
from ocpi22.webhooks import send_to_webhook
from premium import requires_premium

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
            serializer = EvseSerializer(evse, context={'version': request.version})
            return OCPIResponse(serializer.data)

        elif request.method in ('PATCH', 'PUT'):
            data = request.data
            readonly_fields = ('uid', 'evse_id')
            # Remove readonly fields from the incoming data
            for f in readonly_fields:
                data.pop(f, None)

            partial = bool(request.method == 'PATCH')

            serializer = EvseSerializer(evse, data=data, partial=partial, context={'version': request.version})
            if serializer.is_valid():
                serializer.save()
                return OCPIResponse(serializer.data)
            else:
                return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST,
                                    status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

        return OCPIResponse(http_status=status.HTTP_400_BAD_REQUEST,
                            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)


class LocationViewSet(GenericViewSet):
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['country_code', 'party_id', 'parking_type', 'city', 'publish', 'facilities', 'country']
    pagination_class = OCPIPaginationAndHeaders
    root_view_name = 'locations'
    renderer_classes = RENDERERS
    versioning_class = OCPIVersioning
    queryset = Location.objects.all().order_by('created')
    serializer_class = LocationSerializer221
    lookup_field = "uid"

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'Location {self.kwargs.get("uid")}'
        if self.name:
            return f'{self.name.capitalize()}'
        return 'Locations'

    @requires_premium
    def list(self, request, *args, **kwargs):
        serializer_class = self.get_location_serializer(request)
        serializer = serializer_class(self.paginator.paginate_queryset(self.queryset, request),
                                      many=True, context={'version': request.version})
        return self.paginator.get_paginated_response(serializer.data)

    @staticmethod
    def get_object(uid=None) -> Location:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Location, uid=uid)

    @transaction.atomic
    @action(methods=['GET', 'PATCH', 'PUT'], detail=False, url_name='by-evse-id',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)/(?P<evse_id>[^/.]+)')
    @requires_premium
    def by_evse_id(self, request, country_code, party_id, uid, evse_id, **_kwargs) -> OCPIResponse:
        evse: Evse = get_object_or_404(Evse, uid=evse_id, location__uid=uid)
        location: Location = evse.location

        if location.party_id != party_id or location.country_code != country_code:
            return OCPIResponse(
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                status_message='The EVSE is not owned by the specified party or is not in the specified country')

        if request.method == 'GET':
            serializer = EvseSerializer(evse, context={'version': request.version})
            return OCPIResponse(serializer.data)

        elif request.method in ('PATCH', 'PUT'):
            data = request.data
            readonly_fields = ['evse_id']
            # Remove readonly fields from the incoming data
            for f in readonly_fields:
                data.pop(f, None)

            data.update(dict(uid=evse_id, country_code=country_code, party_id=party_id))

            partial = request.method == 'PATCH'

            serializer = EvseSerializer(evse, data=data, partial=partial, context={'request': request})
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

    @transaction.atomic
    @requires_premium
    def put(self, request, data=None, **_kwargs):
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
            serializer = LocationSerializer221(location, data=data, context={'version': request.version})
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

    @transaction.atomic
    @action(methods=['GET', 'PUT', 'PATCH'], detail=False, url_name='by-id',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    @requires_premium
    def location_by_id(self, request: Request, country_code, party_id, uid, **_kwargs) -> OCPIResponse:
        location = get_object_or_404(Location,
                                     country_code=country_code,
                                     party_id=party_id,
                                     uid=uid)

        if request.method == 'GET':
            serializer_class = self.get_location_serializer(request)
            serializer = serializer_class(location, context={'version': request.version})
            return OCPIResponse(serializer.data)

        elif request.method in ('PUT', 'PATCH'):
            partial = request.method == 'PATCH'

            serializer = LocationSerializer(location,
                                            data=request.data.get('data', request.data),
                                            partial=partial,
                                            context={'request': request, 'version': request.version})
            if serializer.is_valid():
                serializer.save()
                return OCPIResponse(serializer.data)
            else:
                return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST,
                                    status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

        return OCPIResponse(http_status=status.HTTP_400_BAD_REQUEST,
                            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    @staticmethod
    def get_location_serializer(request):
        if request.version == '2.2':
            messages.info(request,
                          'Please note that 2-phase connectors are missing in OCPI 2.2, so they are mapped to 1-phase. '
                          'Also, the state is missing from the OCPI 2.2 postal address and the '
                          'START_SESSION_CONNECTOR_REQUIRED capability is filtered out.')
            return LocationSerializer
        return LocationSerializer221
