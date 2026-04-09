from logging import getLogger

from django.core.validators import RegexValidator
from rest_framework import status
from rest_framework.viewsets import GenericViewSet
from rest_framework.generics import get_object_or_404

from ocpi22.choices import OcpiRolesEnum
from ocpi22.decorators import (
    requires_sender_role,
    requires_credentialsrole,
    requires_last_updated,
)
from ocpi22.locations.serializers import EvseSerializer, ConnectorSerializer
from ocpi22.locations.services import LocationService
from ocpi22.messages import messages
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.msp.serializers import MSPChargePointStatusCallbackSerializer
from ocpi22.ocpi.auth import OcpiAuthTypes
from ocpi22.util import OCPIVersioning, OCPIListModelMixin
from ocpi22.ocpi.util import (
    OCPIResponse,
    Ocpi,
    OCPIPaginationAndHeaders,
    OCPIUrlParametersRequiredResponse,
    OCPIBadRequestResponse,
)

# Todo: PATCH & PUT Connector
# Todo: DELETE Tariff

from ocpi22.legacy_webhooks import send_to_webhook_legacy
from ocpiconnector.exception_handler import ocpi_exception_handler
from ocpiconnector.ocpi_identities import ocpi_platform
from util import OCPIVersion

logger = getLogger(__name__)

evse_validator = RegexValidator(
    r"[A-Z]{2}\*[A-Za-z0-9]{3}\*[E][A-Za-z0-9][A-Za-z0-9\*]{0,30}$",
    message="OCPI evse_id has to contain a valid eMI3 EVSE-ID (NL*EVN*E123456ABCD)",
)


class LocationViewSet(OCPIListModelMixin, GenericViewSet):
    pagination_class = OCPIPaginationAndHeaders
    root_view_name = "locations"
    versioning_class = OCPIVersioning
    lookup_field = "uid"
    queryset = Location.objects.none()

    def get_view_name(self):
        if hasattr(self, "kwargs") and "uid" in self.kwargs:
            return f"Location {self.kwargs.get('uid')}"
        if self.name:
            return f"{self.name.capitalize()}"
        return "Locations"

    def get_queryset(self):
        credentials = getattr(self.request, "credentials", None)
        prefetch_fields = (
            "evses",
            "evses__connectors",
            "evses__connectors__tariff_ids",
        )
        if ocpi_platform.is_hub and hasattr(self, "request"):
            queryset = (
                Location.objects.prefetch_related(*prefetch_fields)
                .partner_filter(self.request)
                .exclude(publish=False)
                .exclude(roaming_enabled=False)
                .order_by("created")
            )
        else:
            queryset = (
                Location.objects.prefetch_related(*prefetch_fields)
                .exclude(publish=False)
                .order_by("created")
            )

            ocpi_party = getattr(self.request, "ocpi_party", None)
            # ocpi_party is None when the basic auth is used
            if ocpi_party and ocpi_party.role not in ["NAP", "NSP", "CPO"]:
                queryset = queryset.exclude(roaming_enabled=False)

        queryset = LocationService.get_allowed_locations_queryset(credentials, queryset)
        return queryset

    @ocpi_exception_handler
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @staticmethod
    def get_object(uid=None) -> None:
        pass

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.CPO)
    @requires_last_updated
    def patch(self, *args, **kwargs):
        return self.put(*args, patch=True, **kwargs)

    @ocpi_exception_handler
    @requires_credentialsrole
    def get(self, request, credentialsrole, uid, *_args, **_kwargs):
        """Respond to GET for a specified location"""
        serializer = self.get_serializer_class()(
            self.get_queryset().get(uid__iexact=str(uid), ocpi_master=credentialsrole),
            context={"version": request.version, "request": request},
        )
        return OCPIResponse(serializer.data)

    @ocpi_exception_handler
    @requires_sender_role([OcpiRolesEnum.CPO, OcpiRolesEnum.HUB])
    @requires_credentialsrole
    def put(
        self,
        request,
        data,
        credentialsrole,
        uid=None,
        patch=False,
        version="2.2.1",
        credentials=None,
        **_kwargs,
    ):
        if request and not request.party_specified_in_url:
            return OCPIUrlParametersRequiredResponse("location")

        if uid and uid != data.get("id"):
            raise ValueError("Location ID in URL does not match Location ID in payload")

        uid = uid or data.get("id")

        if not credentials and request and hasattr(request, "credentials"):
            credentials = request.credentials

        return self.save_or_update(
            request, data, credentialsrole, uid, patch, version, credentials
        )

    def save_or_update(
        self,
        request,
        data,
        credentialsrole,
        uid,
        patch=False,
        version="2.2.1",
        credentials=None,
    ):
        existing_location: Location = Location.get_if_exists(
            uid__iexact=uid, ocpi_master=credentialsrole
        )

        serializer_class = Location.get_serializer_class(version)
        serializer = serializer_class(
            instance=existing_location,
            data=data,
            partial=patch,
            context={
                "version": version,
                "credentials": credentials,
                "party": credentialsrole.get_party(),
                "request": request,
                "credentialsrole": credentialsrole,
            },
        )
        if serializer.is_valid():
            created = bool(not existing_location)
            logger.info(
                f"{'Creating' if created else 'Updating'}"
                f" Location {credentialsrole} - {uid}."
            )
            saved_location = serializer.save(ocpi_master=credentialsrole)
            saved_location.send_hub_updates()
            Location.objects.prefetch_related(
                "evses", "evses__connectors", "evses__connectors__tariff_ids"
            ).get(pk=saved_location.pk)
            send_to_webhook_legacy(
                saved_location, MSPChargePointStatusCallbackSerializer
            )
            http_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK

            # Was Location posted from the CPO backend using OCPI Locations endpoint, not from a roaming partner?
            if request.ocpi_auth == OcpiAuthTypes.NONE and ocpi_platform.is_cpo:
                saved_location.send_updates(data=serializer.data)

            return OCPIResponse(serializer.data, http_status=http_status)
        else:
            return OCPIResponse(
                errors=serializer.errors,
                http_status=status.HTTP_400_BAD_REQUEST,
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            )

    def get_serializer_class(self, *_args, **_kwargs):
        request = self.request
        version = OCPIVersion(request.version)
        assert version, "OCPI version is required"
        if version == "2.2":
            messages.info(
                request,
                "Please note that 2-phase connectors are missing "
                "in OCPI 2.2, so they are mapped to 1-phase. "
                "Also, the state is missing from the OCPI 2.2 postal address and the "
                "START_SESSION_CONNECTOR_REQUIRED capability is filtered out.",
            )
        return Location.get_serializer_class(version.pure_number)


class ConnectorViewSet(GenericViewSet):
    pagination_class = OCPIPaginationAndHeaders
    root_view_name = "connectors"
    versioning_class = OCPIVersioning
    lookup_field = "uid"
    queryset = Connector.objects.none()
    serializer_class = ConnectorSerializer

    def get_view_name(self):
        if hasattr(self, "kwargs") and "uid" in self.kwargs:
            return f"Connector {self.kwargs.get('uid')}"
        if self.name:
            return f"{self.name.capitalize()}"
        return "Connectors"

    @ocpi_exception_handler
    @requires_last_updated
    def patch(self, *args, **kwargs) -> OCPIResponse:
        return self.put(*args, patch=True, **kwargs)

    @ocpi_exception_handler
    @requires_credentialsrole
    def get(
        self, request, credentialsrole, uid, evse_uid, connector_uid, *_args, **_kwargs
    ) -> OCPIResponse:
        """Serve a GET request for a specific EVSE"""
        connector: Connector = get_object_or_404(
            Connector,
            evse__uid=evse_uid,
            evse__location__uid=uid,
            uid=connector_uid,
            evse__location__ocpi_master=credentialsrole,
        )
        serializer = self.serializer_class(
            connector, context={"version": request.version, "request": request}
        )
        return OCPIResponse(serializer.data)

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.CPO)
    def put(
        self,
        request,
        uid,
        evse_uid,
        connector_uid,
        patch=False,
        credentialsrole=None,
        *_args,
        **_kwargs,
    ) -> OCPIResponse:
        credentialsrole = credentialsrole or getattr(request, "credentialsrole", None)
        assert (
            credentialsrole
        ), "Credentials role is required for ConnectorViewSet.put()"
        if connector_uid != request.data.get("id"):
            return OCPIBadRequestResponse(
                "Connector UID in URL does not match Connector UID in payload"
            )
        connector: Connector = Connector.get_if_exists(
            uid=connector_uid,
            evse__uid=evse_uid,
            evse__location__uid=uid,
            evse__location__ocpi_master=credentialsrole,
        )

        data = request.data

        # Remove readonly fields from the incoming data, but only if the Connector already exists
        readonly_fields = ["connector_uid"] if connector else []
        for f in readonly_fields:
            data.pop(f, None)

        serializer = self.serializer_class(
            instance=connector,
            data=data,
            partial=patch,
            context={"request": request, "credentialsrole": credentialsrole},
        )
        if serializer.is_valid():
            evse: Evse = get_object_or_404(
                Evse,
                location__uid=uid,
                uid=evse_uid,
                location__ocpi_master=credentialsrole,
            )
            serializer.save(evse=evse)
            return OCPIResponse(serializer.data)
        else:
            return OCPIResponse(
                errors=serializer.errors,
                http_status=status.HTTP_400_BAD_REQUEST,
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            )


class EvseViewSet(GenericViewSet):
    pagination_class = OCPIPaginationAndHeaders
    root_view_name = "evses"
    versioning_class = OCPIVersioning
    lookup_field = "uid"
    queryset = Evse.objects.none()

    def get_view_name(self):
        if hasattr(self, "kwargs") and "uid" in self.kwargs:
            return f"Evse {self.kwargs.get('uid')}"
        if self.name:
            return f"{self.name.capitalize()}"
        return "Evse"

    @ocpi_exception_handler
    @requires_last_updated
    def patch(self, *args, **kwargs) -> OCPIResponse:
        return self.put(*args, patch=True, **kwargs)

    @ocpi_exception_handler
    @requires_credentialsrole
    def get(
        self, request, credentialsrole, uid, evse_uid, *_args, **_kwargs
    ) -> OCPIResponse:
        """Serve a GET request for a specific EVSE"""
        evse: Evse = get_object_or_404(
            Evse, uid=evse_uid, location__uid=uid, location__ocpi_master=credentialsrole
        )
        serializer = EvseSerializer(
            evse, context={"version": request.version, "request": request}
        )
        return OCPIResponse(serializer.data)

    @ocpi_exception_handler
    @requires_sender_role(OcpiRolesEnum.CPO)
    def put(
        self,
        request,
        uid,
        evse_uid,
        patch=False,
        credentialsrole=None,
        *_args,
        **_kwargs,
    ) -> OCPIResponse:
        credentialsrole = credentialsrole or getattr(request, "credentialsrole", None)
        assert credentialsrole, "Credentialsrole is required for EvseViewSet.put()"

        evse: Evse = Evse.get_if_exists(
            uid=evse_uid, location__uid=uid, location__ocpi_master=credentialsrole
        )
        if not evse:
            return OCPIBadRequestResponse("EVSE not found")

        location: Location = evse.location
        data = request.data

        # Remove readonly fields from the incoming data, but only if the EVSE already exists
        readonly_fields = ["evse_id"] if evse else []
        for f in readonly_fields:
            data.pop(f, None)

        # data.update({'uid': evse_uid, 'country_code': request.credentialsrole.country_code,
        #              'party_id': request.credentialsrole.party_id})

        serializer = EvseSerializer(
            instance=evse, data=data, partial=patch, context={"request": request}
        )
        if serializer.is_valid():
            evse = serializer.save(location=location)
            data = {
                "location_id": location.uid,
                "evse_id": evse.uid,
                "status": evse.status,
            }
            if ocpi_platform.is_emsp:
                send_to_webhook_legacy(
                    data,
                    MSPChargePointStatusCallbackSerializer,
                    ocpi_master=credentialsrole,
                )
            return OCPIResponse(serializer.data)
        else:
            return OCPIResponse(
                errors=serializer.errors,
                http_status=status.HTTP_400_BAD_REQUEST,
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            )

    def get_serializer_class(self, *_args, **_kwargs):
        request = self.request
        version = OCPIVersion(request.version)
        assert version, "OCPI version is required"
        if version == "2.2":
            messages.info(
                request,
                "Please note that 2-phase connectors are missing in OCPI 2.2, so they are mapped to 1-phase. "
                "Also, the state is missing from the OCPI 2.2 postal address and the "
                "START_SESSION_CONNECTOR_REQUIRED capability is filtered out.",
            )
        return Location.get_serializer_class(version.pure_number)
