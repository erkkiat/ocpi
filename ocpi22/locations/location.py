from django.db.models import Q

import ocpi22.logging as logging

from django.core.validators import RegexValidator
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
from ocpi22.ocpi.util import OCPIResponse, Ocpi, OCPIPaginationAndHeaders, OCPIUrlParametersRequiredResponse, \
    OCPIBadRequestResponse, OCPINotFoundResponse

# Todo: PATCH & PUT Connector
# Todo: DELETE Tariff

from ocpi22.webhooks import send_to_webhook
from ocpiconnector.exception_handler import ocpi_exception_handler
from ocpiconnector.ocpi_identities import ocpi_platform
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
    queryset = Location.objects.none()

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'Location {self.kwargs.get("uid")}'
        if self.name:
            return f'{self.name.capitalize()}'
        return 'Locations'

    def get_queryset(self):
        criteria = Q()
        if ocpi_platform.is_hub:
            agreed_parties = get_partners(self.request)
            criteria = Q(ocpi_master__in=agreed_parties)
        return Location.objects.filter(criteria).order_by('created')

    @ocpi_exception_handler
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
            version='2.2.1', logentry=None, credentials=None, **_kwargs):

        if request and not request.party_specified_in_url:
            return OCPIUrlParametersRequiredResponse('location')

        uid = uid or data.get('id')

        if not credentials and request and hasattr(request, 'credentials'):
            credentials = request.credentials

        return self.save_or_update(request, data, credentialsrole, uid, patch, version, logentry, credentials)

    @staticmethod
    def save_or_update(request, data, credentialsrole, uid, patch=False,
            version='2.2.1', logentry=None, credentials=None):

        assert uid, 'Location ID is a required parameter for LocationViewSet.save_or_update()'
        existing_location: Location = Location.get_if_exists(
            uid__iexact=uid, ocpi_master=credentialsrole
        )

        serializer_class = Location.get_serializer_class(version)
        serializer = serializer_class(instance=existing_location, data=data, partial=patch,
                                      context={'version': version, 'credentials': credentials,
                                               'party': credentialsrole.party, 'request': request})
        if serializer.is_valid():
            created = bool(not existing_location)
            logging.info(f'{"Creating" if created else "Updating"}'
                         f' Location {credentialsrole} - {uid}.', log_to_admin=True, logentry=logentry)
            saved_location = serializer.save(ocpi_master=credentialsrole)
            saved_location.send_hub_updates()
            send_to_webhook(saved_location, MSPChargePointStatusCallbackSerializer)
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
        if evse_uid != request.data.get('uid'):
            return OCPIBadRequestResponse('EVSE UID in URL does not match EVSE UID in payload')
        evse: Evse = Evse.get_if_exists(uid=evse_uid, location__uid=uid,
                                        location__ocpi_master=request.credentialsrole)
        location: Location = Location.get_if_exists(uid=uid, ocpi_master=request.credentialsrole)
        if not location:
            return OCPINotFoundResponse(f'Location with UID "{uid}" not found')

        data = request.data

        # Remove readonly fields from the incoming data, but only if the EVSE already exists
        readonly_fields = ['evse_id'] if evse else []
        for f in readonly_fields:
            data.pop(f, None)

        # data.update({'uid': evse_uid, 'country_code': request.credentialsrole.country_code,
        #              'party_id': request.credentialsrole.party_id})

        serializer = EvseSerializer(instance=evse, data=data, partial=patch, context={'request': request})
        if serializer.is_valid():
            evse = serializer.save(location=location)
            data = {
                'location_id': location.uid,
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
