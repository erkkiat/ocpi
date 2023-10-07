from django.db.models import Q

import ocpi22.logging as logging

from django.core.validators import RegexValidator
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.viewsets import GenericViewSet
from rest_framework.generics import get_object_or_404

from certification.decorators import certification_step
from ocpi22.choices import OcpiRolesEnum, OcpiModuleEnum
from ocpi22.decorators import requires_sender_role, requires_credentialsrole, requires_last_updated
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
    @requires_last_updated
    @certification_step(OcpiModuleEnum.LOCATIONS, 'PATCH a Location')
    def patch(self, *args, **kwargs):
        return self.put(*args, patch=True, **kwargs)

    @ocpi_exception_handler
    @requires_premium
    @requires_credentialsrole
    def get(self, request, credentialsrole, uid, *_args, **_kwargs):
        """Respond to GET for a specified location"""
        serializer = self.get_serializer_class()(
            Location.objects.get(uid__iexact=uid, ocpi_master=credentialsrole),
            context={'version': request.version, 'request': request})
        return OCPIResponse(serializer.data)

    @requires_premium
    @ocpi_exception_handler
    @requires_sender_role([OcpiRolesEnum.CPO, OcpiRolesEnum.HUB])
    @requires_credentialsrole
    @certification_step(OcpiModuleEnum.LOCATIONS, 'PUT a Location')
    def put(self, request, data, credentialsrole, uid=None, patch=False,
            version='2.2.1', logentry=None, **_kwargs):
        if not request.party_specified_in_url:
            return OCPIResponseUrlParametersRequired('location')

        uid = uid or data.get('id')
        version = version or request.version

        existing_location: Location = Location.get_if_exists(
            uid__iexact=uid, ocpi_master=credentialsrole
        )
        patch = bool(patch or request.method == 'PATCH')
        serializer_class = Location.get_serializer_class(version)
        serializer = serializer_class(instance=existing_location, data=data, partial=patch,
                                      context={'version': version, 'credentials': request.credentials,
                                               'party': credentialsrole.party, 'request': request})
        if serializer.is_valid():
            created = bool(not existing_location)
            logging.info(f'{"Creating" if created else "Updating"}'
                         f' Location {credentialsrole} - {uid}.', log_to_admin=True, logentry=logentry)
            created_location = serializer.save(ocpi_master=credentialsrole)
            created_location.send_hub_updates()
            http_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            return OCPIResponse(serializer.data, http_status=http_status)
        else:
            return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST,
                                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    def get_serializer_class(self, *_args, **_kwargs):
        request = self.request
        version = OCPIVersion(request.version)
        assert version, 'OCPI version is required'
        if version == '2.2':
            messages.info(request,
                          'Please note that 2-phase connectors are missing '
                          'in OCPI 2.2, so they are mapped to 1-phase. '
                          'Also, the state is missing from the OCPI 2.2 postal address and the '
                          'START_SESSION_CONNECTOR_REQUIRED capability is filtered out.')
        return Location.get_serializer_class(version.pure_number)


class EvseViewSet(GenericViewSet):
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
    @requires_last_updated
    def patch(self, *args, **kwargs) -> OCPIResponse:
        return self.put(*args, patch=True, **kwargs)

    @ocpi_exception_handler
    @requires_premium
    @requires_credentialsrole
    def get(self, request, credentialsrole, uid, evse_uid, *_args, **_kwargs) -> OCPIResponse:
        """Serve a GET request for a specific EVSE"""
        evse: Evse = get_object_or_404(Evse, uid=evse_uid, location__uid=uid,
                                       location__ocpi_master=credentialsrole)
        serializer = EvseSerializer(evse, context={'version': request.version, 'request': request})
        return OCPIResponse(serializer.data)

    @ocpi_exception_handler
    @requires_premium
    @requires_sender_role(OcpiRolesEnum.CPO)
    def put(self, request, uid, evse_uid, patch=False,
            *_args, **_kwargs) -> OCPIResponse:
        evse: Evse = Evse.get_if_exists(uid=evse_uid, location__uid=uid,
                                        location__ocpi_master=request.credentialsrole)
        data = request.data
        readonly_fields = ['evse_id']
        # Remove readonly fields from the incoming data
        for f in readonly_fields:
            data.pop(f, None)

        # data.update({'uid': evse_uid, 'country_code': request.credentialsrole.country_code,
        #              'party_id': request.credentialsrole.party_id})

        serializer = EvseSerializer(instance=evse, data=data, partial=patch, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            data = {
                'location_id': evse.location.uid,
                'evse_id': evse.uid,
                'status': evse.status
            }
            if ocpi_platform.is_emsp:
                send_to_webhook(data, MSPChargePointStatusCallbackSerializer)
            return OCPIResponse(serializer.data)
        else:
            return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST,
                                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    def get_serializer_class(self, *_args, **_kwargs):
        request = self.request
        version = OCPIVersion(request.version)
        assert version, 'OCPI version is required'
        if version == '2.2':
            messages.info(request,
                          'Please note that 2-phase connectors are missing in OCPI 2.2, so they are mapped to 1-phase. '
                          'Also, the state is missing from the OCPI 2.2 postal address and the '
                          'START_SESSION_CONNECTOR_REQUIRED capability is filtered out.')
        return Location.get_serializer_class(version.pure_number)
