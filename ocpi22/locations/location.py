from django.db.models import Q

import ocpi22.logging as logging

from django.core.validators import RegexValidator
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.viewsets import GenericViewSet
from rest_framework.generics import get_object_or_404

from ocpi22.choices import OcpiRolesEnum
from ocpi22.decorators import requires_sender_role
from ocpi22.locations.serializers import EvseSerializer
from ocpi22.messages import messages
from ocpi22.models.location import Location, Evse
from ocpi22.msp.serializers import MSPChargePointStatusCallbackSerializer
from ocpi22.ocpi.partners import get_partners
from ocpi22.rendering import RENDERERS
from ocpi22.util import OCPIVersioning, OCPIListModelMixin
from ocpi22.ocpi.util import OCPIResponse, Ocpi, OCPIPaginationAndHeaders

# Todo: PATCH & PUT Connector
# Todo: DELETE Tariff

from ocpi22.webhooks import send_to_webhook
from ocpiconnector.exception_handler import ocpi_exception_handler
from ocpiconnector.ocpi_identities import Party, ocpi_platform
from premium import requires_premium
from util import OCPIVersion

evse_validator = RegexValidator(r'[A-Z]{2}\*[A-Za-z0-9]{3}\*[E][A-Za-z0-9][A-Za-z0-9\*]{0,30}$',
                                message='OCPI evse_id has to contain a valid eMI3 EVSE-ID (NL*EVN*E123456ABCD)')


class LocationViewSet(OCPIListModelMixin, GenericViewSet):
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['country_code', 'party_id', 'parking_type', 'city', 'publish', 'facilities', 'country']
    pagination_class = OCPIPaginationAndHeaders
    root_view_name = 'locations'
    renderer_classes = RENDERERS
    versioning_class = OCPIVersioning
    lookup_field = "uid"

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'Location {self.kwargs.get("uid")}'
        if self.name:
            return f'{self.name.capitalize()}'
        return 'Locations'

    @requires_premium
    def list(self, *args, **kwargs):
        return super().list(*args, **kwargs)

    @staticmethod
    def get_object(uid=None) -> Location:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Location, uid=uid)

    @requires_premium
    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.CPO)
    def patch(self, *args, **kwargs):
        return self.put(*args, patch=True, **kwargs)

    @ocpi_exception_handler
    @requires_premium
    def get(self, request, country_code, party_id, uid, *_args, **_kwargs):
        serializer = self.get_serializer_class()(
            Location.objects.get(
                country_code__iexact=country_code, party_id__iexact=party_id, uid__iexact=uid,
            ),
            context={'version': request.version, 'request': request})
        return OCPIResponse(serializer.data)

    @requires_premium
    @ocpi_exception_handler
    @requires_sender_role([OcpiRolesEnum.CPO, OcpiRolesEnum.HUB])
    def put(self, request, data=None, country_code=None, party_id=None, uid=None, patch=False,
            version='2.2.1', logentry=None, **_kwargs):
        uid = uid or data.get('id')
        version = version or request.version

        assert uid and country_code and party_id, \
            f'Country code, party_id and id are required when doing a PUT for a Location.'

        existing_location: Location = Location.get_if_exists(
            uid__iexact=uid, ocpi_master=request.credentialsrole
        )
        patch = bool(patch or request.method == 'PATCH')
        serializer_class = Location.get_serializer_class(version)
        serializer = serializer_class(instance=existing_location, data=data, partial=patch,
                                      context={'version': version, 'credentials': request.credentials,
                                               'party': Party(country_code, party_id), 'request': request})
        if serializer.is_valid():
            created = bool(not existing_location)
            logging.info(f'{"Creating" if created else "Updating"}'
                         f' Location {country_code}*{party_id} - {uid}.', log_to_admin=True, logentry=logentry)
            created_location = serializer.save(ocpi_master=request.credentialsrole)
            created_location.send_hub_updates()
            http_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            return OCPIResponse(serializer.data, http_status=http_status)
        else:
            return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST,
                                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    def get_serializer_class(self, *args, **kwargs):
        request = self.request
        version = OCPIVersion(request.version)
        assert version, 'OCPI version is required'
        if version == '2.2':
            messages.info(request,
                          'Please note that 2-phase connectors are missing in OCPI 2.2, so they are mapped to 1-phase. '
                          'Also, the state is missing from the OCPI 2.2 postal address and the '
                          'START_SESSION_CONNECTOR_REQUIRED capability is filtered out.')
        return Location.get_serializer_class(version.pure_number)


class EvseViewSet(GenericViewSet):
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['standard', 'format', 'power_type', 'max_voltage', 'max_amperage', 'max_electric_power']
    pagination_class = OCPIPaginationAndHeaders
    root_view_name = 'evses'
    renderer_classes = RENDERERS
    versioning_class = OCPIVersioning
    lookup_field = "uid"
    queryset = Evse.objects.none()

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'Evse {self.kwargs.get("uid")}'
        if self.name:
            return f'{self.name.capitalize()}'
        return 'Evse'

    @ocpi_exception_handler
    @requires_premium
    @requires_sender_role()
    def patch(self, *args, **kwargs) -> OCPIResponse:
        return self.put(*args, patch=True, **kwargs)

    @ocpi_exception_handler
    @requires_premium
    def get(self, request, country_code, party_id, uid, evse_uid, version='2.2.1', *_args, **_kwargs) -> OCPIResponse:
        evse: Evse = get_object_or_404(Evse, uid=evse_uid, location__uid=uid)
        location: Location = evse.location

        if location.party_id != party_id or location.country_code != country_code:
            return OCPIResponse(
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                status_message='The EVSE is not owned by the specified party or is not in the specified country')

        serializer = EvseSerializer(evse, context={'version': request.version, 'request': request})
        return OCPIResponse(serializer.data)

    @ocpi_exception_handler
    @requires_premium
    @requires_sender_role()
    def put(self, request, country_code, party_id, uid, evse_uid, patch=False,
            version='2.2.1', *_args, **_kwargs) -> OCPIResponse:
        evse: Evse = Evse.objects.get(uid=evse_uid, location__uid=uid,
                                      location__ocpi_master=request.credentialsrole)
        location: Location = evse.location

        if location.party_id != party_id or location.country_code != country_code:
            return OCPIResponse(
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                status_message='The EVSE is not owned by the specified party or is not in the specified country')

        data = request.data
        readonly_fields = ['evse_id']
        # Remove readonly fields from the incoming data
        for f in readonly_fields:
            data.pop(f, None)

        data.update(dict(uid=evse_uid, country_code=country_code, party_id=party_id))

        serializer = EvseSerializer(evse, data=data, partial=patch, context={'request': request})
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

    def get_serializer_class(self, *args, **kwargs):
        request = self.request
        version = OCPIVersion(request.version)
        assert version, 'OCPI version is required'
        if version == '2.2':
            messages.info(request,
                          'Please note that 2-phase connectors are missing in OCPI 2.2, so they are mapped to 1-phase. '
                          'Also, the state is missing from the OCPI 2.2 postal address and the '
                          'START_SESSION_CONNECTOR_REQUIRED capability is filtered out.')
        return Location.get_serializer_class(version.pure_number)
