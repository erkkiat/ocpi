import functools
import json
import uuid
from collections import OrderedDict
from enum import Enum
from urllib.parse import urljoin

from logging import getLogger

from django.contrib.auth.models import Permission
from django.utils.datetime_safe import datetime
from typing import Union

import pytz
import requests
from django.conf import settings
from django.db.models import QuerySet
from django.utils.module_loading import import_string
from rest_framework import status
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import BasePermission, SAFE_METHODS

from ocpi22.choices import OcpiRolesEnum
from rest_framework.response import Response

from ocpi22.ocpi.headers import make_headers
from ocpi22.routing import find_route
from ocpi22.tasks import get_certificate_loaded_request
from ocpiconnector.exceptions import OCPIProtocolError
from ocpiconnector.ocpi_identities import (
    ocpi_identities,
    ocpi_platform,
    get_our_identity,
    get_our_party,
)
from ocpiconnector.party import Party
from util import OCPIVersion, with_trailing_slash

logger = getLogger(__name__)


def get_serializer(ocpi_serializer_class):
    if isinstance(ocpi_serializer_class, str):
        return import_string(ocpi_serializer_class)
    return ocpi_serializer_class


class OcpiModule:
    # The serializer class to use when sending updates to other OCPI parties
    ocpi_serializer_class = None
    ocpi_serializer_classes = {}

    # The module name to be used when looking for endpoints to send updates to
    ocpi_module_name = None

    # This determines which identity of ours we will use when sending updates for this type of object
    ocpi_object_owner = None

    # Who holds the master data for this object
    ocpi_master = None

    # A list of subscribers for objects of this type
    subscribers = None

    # A list of roles to receive updates on this type of objects
    # If you set this to INTERESTED_PARTIES, updates will only be sent to the party which is billed for the transaction
    send_updates_to = []

    INTERESTED_PARTIES = -1

    @classmethod
    def get_owner_identity(cls) -> str:
        if ocpi_platform.is_hub:
            return get_our_identity("HUB")

        assert hasattr(cls, "ocpi_object_owner"), (
            f"The OCPI object {cls} needs to have ocpi_object_owner specified "
            f"so that the sender identity is clear when sending updates to other parties."
        )
        return ocpi_identities.get(cls.ocpi_object_owner, default="*")

    def update_last_updated(self):
        """For objects owned by us, set the current date and time to last_updated"""
        if self.is_ours():
            recursive_update_last_updated(self)

    def post_process_after_update_or_create(self, *_args, **_kwargs) -> None:
        assert (
            hasattr(self, "ocpi_serializer_class")
            and hasattr(self, "ocpi_module_name")
            and hasattr(self, "send_updates_to")
        ), (
            f"OCPI object class {type(self)} must have an ocpi_serializer_class (str), "
            f"ocpi_module_name (str) and send_updates_to (roles list) specified."
        )

        if hasattr(self, "is_ours") and self.is_ours():
            recursive_update_last_updated(self)

        if not hasattr(self, "update_sent") and self.is_ours():
            if not hasattr(self, "archived") or not self.archived:
                self.send_updates(method=getattr(self, "update_method", "PUT"))
                # Send update only once
                setattr(self, "update_sent", True)

    def send_updates(
        self, data=None, method="put", path_components=[], send_updates_to=None
    ) -> None:
        """
        Find all endpoints interested in OCPI object updates and send update in a background task.
        To disable updates, set env SEND_UPDATES to false
        """
        if not getattr(self, "updates_sent", None):
            # The URL for this specific location has URL parameters, for example .../BE/SMP/1234
            path_components = path_components or [
                self.ocpi_master.country_code,
                self.ocpi_master.party_id,
                self.uid,
            ]

            if settings.SEND_UPDATES:
                # Do we possess the role who controls the master data for this type of object or are we acting as HUB
                if (
                    self.ocpi_object_owner not in ocpi_identities.roles
                    and not ocpi_platform.is_hub
                ):
                    logger.warning(
                        f"We don't possess the role required for sending updates for {type(self)}."
                    )
                    return

                if not send_updates_to:
                    send_updates_to = self.send_updates_to

                if send_updates_to == OcpiModule.INTERESTED_PARTIES:
                    logger.info("Sending updates to INTERESTED PARTIES")
                    self.send_update_to_interested_parties(
                        method=method, path_components=path_components
                    )
                else:
                    logger.info("Sending updates to ALL connected parties")
                    self.send_all_updates(
                        data=data,
                        method=method,
                        path_components=path_components,
                        send_updates_to=send_updates_to,
                    )

                setattr(self, "updates_sent", True)

    def send_all_updates(
        self,
        data=None,
        method="put",
        path_components=[],
        ocpi_module_name=None,
        send_updates_to=None,
    ) -> bool:
        if not settings.SEND_UPDATES:
            return True
        # Todo: Use sender identity, not our HUB identity
        from ocpi22.credentials.util import find_endpoints_by_roles

        if not send_updates_to:
            send_updates_to = self.send_updates_to

        our_country_code, our_party_id = self.get_owner_identity().split("*")
        logger.info(
            f"Sending updates for {self} from {our_country_code}*{our_party_id} to {send_updates_to}"
        )

        ocpi_module_name = ocpi_module_name or self.ocpi_module_name
        if isinstance(send_updates_to, (list, tuple)):
            endpoints = find_endpoints_by_roles(send_updates_to, ocpi_module_name)
            for url, token_base64, country_code, party_id, credentials in endpoints:
                from ocpi22.models.location import Location
                from ocpi22.credentials.services import CredentialsService

                if isinstance(self, Location):
                    if not credentials:
                        logger.error(f"Credentials missing for endpoint {url}")
                        continue
                    if not CredentialsService.is_location_allowed(
                        credentials, self.uid
                    ):
                        logger.info(
                            f"Skipping sending update for {self} to {country_code}*{party_id} as it's not in allowed locations of credentials {credentials.id}"
                        )
                        continue
                try:
                    if path_components:
                        url = urljoin(
                            with_trailing_slash(url), "/".join(path_components)
                        )

                    data = data or self.serialize(credentials.version)
                    logger.info(
                        f"Sending updates for {self} from {our_country_code}*{our_party_id} to {self.send_updates_to}, with credentials {credentials.id}"
                    )
                    logger.info(f"Sending update to URL {url}")
                    self.send_background_update(
                        data,
                        url,
                        token_base64,
                        to=Party(country_code, party_id),
                        sender=Party(our_country_code, our_party_id),
                        method=method,
                        credentials=credentials,
                    )
                except Exception:
                    logger.exception(f"Unable to send update to {url}")
            return True
        logger.error(
            f"{settings.HOSTNAME}: Unable to send updates for {self}, don't know where to send."
        )
        return False

    @classmethod
    def send_background_update(
        cls,
        data: dict,
        url,
        token_base64,
        to: Party,
        sender: Party,
        method="put",
        credentials=None,
    ):
        if not settings.SEND_UPDATES:
            return
        logger.info(
            f"Received credentials id in send_background_update, {credentials.id}"
        )
        if url and token_base64 and to and sender:
            from ocpi22.tasks import send_ocpi_request

            args = (
                json.dumps(data, default=str),
                url,
                token_base64,
                to.country_code,
                to.party_id,
                sender.country_code,
                sender.party_id,
                method,
                credentials.id,
            )
            send_ocpi_request.apply_async(
                args, retry=False, title=f"{cls.ocpi_module_name.value} update"
            )
        else:
            logger.error(f"Skipping send for {cls} due to missing parameters")

    def send_hub_updates(self) -> None:
        if ocpi_platform.is_hub and settings.SEND_UPDATES:
            logger.info(f"Sending HUB updates for {self}.")
            self.send_updates()  # Todo: Use sender identity, not our HUB identity

    @classmethod
    def get_serializer_class(cls, version: Union[OCPIVersion, str]):
        """
        >>> from ocpi22.models.location import Location
        >>> Location.get_serializer_class('2.2.1')
        <class 'ocpi22.locations.serializers.LocationSerializer221'>
        >>> Location.get_serializer_class('2.2')
        <class 'ocpi22.locations.serializers.LocationSerializer'>
        """
        version = OCPIVersion(version)
        serializer_class = None
        if hasattr(cls, "ocpi_serializer_classes"):
            serializer_class = cls.ocpi_serializer_classes.get(version.pure_number)
        if not serializer_class:
            serializer_class = cls.ocpi_serializer_class
        if isinstance(serializer_class, str):
            serializer_class = import_string(serializer_class)
        assert (
            serializer_class
        ), f"No serializer class found for {cls} for version {version}"
        return serializer_class

    @functools.lru_cache(maxsize=None)
    def serialize(self, version: Union[OCPIVersion, str]) -> dict:
        version = OCPIVersion(version)
        serializer_class = self.__class__.get_serializer_class(version.pure_number)
        serializer = serializer_class(self)
        return serializer.data

    def route_single_update_message(
        self, method, to, data=None, path_components=[], credentials=None
    ) -> None:
        sender = Party(*(self.get_owner_identity().split("*")))
        route = find_route(
            to, self.ocpi_module_name, add_path="/".join(path_components)
        )
        if route:
            data = data or self.serialize(version=route.version.pure_number)
            self.send_background_update(
                data,
                route.url,
                route.token_base64,
                to=to,
                sender=sender,
                method=method,
                credentials=credentials,
            )
        else:
            logger.error(f"Unable to find route to {str(to)}")

    def send_update_to_interested_parties(self, *args, method="PUT", **kwargs) -> None:
        credentials = getattr(self, "credentials", None)
        if credentials:
            if not hasattr(self, "billed_to"):
                logger.error(
                    f"Object #{self.uid} - {self} has no billed_to, cannot send updates to interested parties",
                )
                return
            # self.send_subscriber_updates(*args, **kwargs)  # This was used by a Dutch startup, no longer a customer
            to = self.billed_to.get_party()
            return self.route_single_update_message(
                to=to, method=method, credentials=credentials, **kwargs
            )
        else:
            logger.error(
                f"Object #{self.uid} - {self} has no credentials, cannot send updates to interested parties"
            )
            # Todo: Stop charging session, cannot bill

    # @cachedmethod(cachetools.cache)
    def _get_subscriber_parties(self, partylist=None) -> list:
        partylist = partylist or self.subscribers or []
        return [Party(*(p.split("*"))) for p in partylist if p]


def ocpi_post(
    url, token_base64, to: Party, sender: Party, *args, **kwargs
) -> requests.Response:
    data = ""
    if "data" in kwargs:
        data = kwargs.pop("data")
    response = requests.post(
        url,
        *args,
        **kwargs,
        json=data,
        timeout=25,
        headers=make_headers(token_base64, to, sender),
    )
    logger.info(f"Posting to {url}, response {response.status_code}")
    if response.status_code >= 300:
        try:
            data = response.json()
            logger.error(
                f"{settings.HOSTNAME}: `{url}` - {response.status_code} - {data}"
            )
            # raise ValidationError(data.get("status_message") or f'Unknown error: {data}')
        except (
            Exception,
            requests.exceptions.JSONDecodeError,
            requests.exceptions.Timeout,
        ):
            logger.exception("Ocpi post request failed")
    return response


def format_ocpi_response(
    status_code: int = 1000, status_message: str = "", data=""
) -> dict:
    return dict(
        status_code=status_code,
        status_message=status_message,
        timestamp=datetime.now(pytz.utc).strftime(settings.OCPI_DATE_FORMAT),
        data=data,
    )


class Ocpi:
    OK = 1000

    class ClientError:
        # Todo: Check that these are used
        GENERIC_CLIENT_ERROR = 2000
        INVALID_OR_MISSING_PARAMETERS = 2001
        NOT_ENOUGH_INFORMATION = 2002
        UNKNOWN_LOCATION = 2003
        UNKNOWN_TOKEN = 2004

    class ServerError:
        GENERIC_SERVER_ERROR = 3000
        UNABLE_TO_USE_CLIENTS_API = 3001
        UNSUPPORTED_VERSION = 3002
        NO_MATCHING_ENDPOINTS = 3003

    class HubError:
        UNKNOWN_RECEIVER = 4001
        TIMEOUT_ON_FORWARDED_REQUEST = 4002
        CONNECTION_PROBLEM = 4003

    class Modules:
        LOCATIONS = "locations"
        TARIFFS = "tariffs"
        TOKENS = "tokens"
        CREDENTIALS = "credentials"
        SESSIONS = "sessions"
        CDRS = "cdrs"
        COMMANDS = "commands"
        CLIENTINFO = "hubclientinfo"

    STANDARD_CHOICES = (
        ("IEC_62196_T2", "Type 2"),
        ("IEC_62196_T2_COMBO", "CCS type 2"),
        ("CHADEMO", "CHAdeMO"),
        ("IEC_62196_T1", 'IEC 62196 Type 1 "SAE J1772"'),
        ("IEC_62196_T1_COMBO", "CCS type 1"),
        ("IEC_62196_T3A", "IEC 62196 Type 3A"),
        ("IEC_62196_T3C", 'IEC 62196 Type 3C "Scame"'),
        ("DOMESTIC_A", 'Type "A", NEMA 1-15, 2 pins'),
        ("DOMESTIC_B", 'Type "B", NEMA 5-15, 3 pins'),
        ("DOMESTIC_C", 'Type "C", CEE 7 / 17, 2 pins'),
        ("DOMESTIC_D", 'Type "D", 3 pin'),
        ("DOMESTIC_E", 'Type "E", CEE 7 / 5 3 pins'),
        ("DOMESTIC_F", 'Type "F", CEE 7 / 4, Schuko, 3 pins'),
        ("DOMESTIC_G", 'Type "G", BS 1363, Commonwealth, 3 pins'),
        ("DOMESTIC_H", 'Type "H", SI-32, 3 pins'),
        ("DOMESTIC_I", 'Type "I", AS 3112, 3 pins'),
        ("DOMESTIC_J", 'Type "J", SEV 1011, 3 pins'),
        ("DOMESTIC_K", 'Type "K", DS 60884-2-D1, 3 pins'),
        ("DOMESTIC_L", 'Type "L", CEI 23-16-VII, 3 pins'),
        ("IEC_60309_2_single_16", "IEC 60309-2 single phase 16 A (blue)"),
        ("IEC_60309_2_three_16", "IEC 60309-2 three phase 16 A (red)"),
        ("IEC_60309_2_three_32", "IEC 60309-2 three phase 32 A (red)"),
        ("IEC_60309_2_three_64", "IEC 60309-2 three phase 64 A (red)"),
        ("PANTOGRAPH_BOTTOM_UP", "On-board Bottom-up-Pantograph"),
        ("PANTOGRAPH_TOP_DOWN", "Off-board Top-down-Pantograph"),
        ("TESLA_R", 'Tesla "Roadster"-type'),
        ("TESLA_S", 'Tesla "Model-S"-type'),
    )

    class Standard(Enum):
        IEC_62196_T2 = "IEC_62196_T2"
        IEC_62196_T2_COMBO = "IEC_62196_T2_COMBO"
        CHADEMO = "CHADEMO"
        IEC_62196_T1 = "IEC_62196_T1"
        IEC_62196_T1_COMBO = "IEC_62196_T1_COMBO"
        IEC_62196_T3A = "IEC_62196_T3A"
        IEC_62196_T3C = "IEC_62196_T3C"
        DOMESTIC_A = "DOMESTIC_A"
        DOMESTIC_B = "DOMESTIC_B"
        DOMESTIC_C = "DOMESTIC_C"
        DOMESTIC_D = "DOMESTIC_D"
        DOMESTIC_E = "DOMESTIC_E"
        DOMESTIC_F = "DOMESTIC_F"
        DOMESTIC_G = "DOMESTIC_G"
        DOMESTIC_H = "DOMESTIC_H"
        DOMESTIC_I = "DOMESTIC_I"
        DOMESTIC_J = "DOMESTIC_J"
        DOMESTIC_K = "DOMESTIC_K"
        DOMESTIC_L = "DOMESTIC_L"
        IEC_60309_2_single_16 = "IEC_60309_2_single_16"
        IEC_60309_2_three_16 = "IEC_60309_2_three_16"
        IEC_60309_2_three_32 = "IEC_60309_2_three_32"
        IEC_60309_2_three_64 = "IEC_60309_2_three_64"
        PANTOGRAPH_BOTTOM_UP = "PANTOGRAPH_BOTTOM_UP"
        PANTOGRAPH_TOP_DOWN = "PANTOGRAPH_TOP_DOWN"
        TESLA_R = "TESLA_R"
        TESLA_S = "TESLA_S"

    FORMAT_CHOICES = (
        ("SOCKET", "Socket"),
        ("CABLE", "Cable"),
    )

    class Format(Enum):
        SOCKET = "SOCKET"
        CABLE = "CABLE"

    POWERTYPES = dict(CHADEMO="DC", IEC_62196_T2_COMBO="DC", IEC_62196_T2="AC_3_PHASE")

    _POWERTYPE_DATA = (
        ("AC_1_PHASE", "AC 1-phase", 1),
        ("AC_2_PHASE", "AC 2-phase", 2),
        ("AC_3_PHASE", "AC 3-phase", 3),
        ("AC_2_PHASE_SPLIT", "AC 2-phase split", 2),
        ("DC", "DC", 3),
    )

    POWERTYPE_CHOICES_221 = [
        (x[0], x[1]) for x in _POWERTYPE_DATA
    ]  # For model choices: (('AC_1_PHASE', 'AC 1-phase'), ... )

    POWERTYPE_PHASES = dict(
        (x[0], x[2]) for x in _POWERTYPE_DATA
    )  # For power calculation: (('AC_1_PHASE', 1), ... )

    class PowerType(Enum):
        AC_1_PHASE = "AC_1_PHASE"
        AC_2_PHASE = "AC_2_PHASE"
        AC_3_PHASE = "AC_3_PHASE"
        AC_2_PHASE_SPLIT = "AC_2_PHASE_SPLIT"
        DC = "DC"


class OCPIResponse(Response):
    def __init__(
        self,
        data="",
        status_code=Ocpi.OK,
        status_message="",
        http_status=status.HTTP_200_OK,
        errors=None,
        *args,
        **kwargs,
    ):
        if status_code == Ocpi.OK and not status_message:
            status_message = "Success"
        if isinstance(status_message, list):
            status_message = ", ".join([s for s in status_message])
        if isinstance(errors, dict):
            status_message = ", ".join(
                [f"{field}: {error}" for field, error in errors.items()]
            )
            data = errors  # This is a courtacy, it's not OCPI compliant
            status_code = Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS
            http_status = status.HTTP_400_BAD_REQUEST
            logger.error(f"{settings.HOSTNAME}: {status_message}")
        result = format_ocpi_response(status_code, status_message, data)
        if status_code != Ocpi.OK or http_status >= status.HTTP_401_UNAUTHORIZED:
            logger.error(str(result))
        super().__init__(
            result, status=kwargs.pop("status", http_status), *args, **kwargs
        )


class OCPIUrlParametersRequiredResponse(OCPIResponse):
    def __init__(self, module_name):
        super().__init__(
            status_message="According to OCPI 2.2 specification, the country_code, "
            f"party_id and {module_name} uid SHALL be provided as URL segments. For example: "
            f"PUT To URL: https://www.server.com/ocpi/2.2/{module_name}s/NL/TNM/12",
            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            http_status=status.HTTP_400_BAD_REQUEST,
        )


class OCPIBadRequestResponse(OCPIResponse):
    def __init__(self, message="no message supplied", *args, **kwargs):
        super().__init__(
            *args,
            status_code=kwargs.pop(
                "status_code", Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS
            ),
            http_status=kwargs.pop("http_status", status.HTTP_400_BAD_REQUEST),
            status_message=kwargs.pop("status_message", f"Bad request: {message}"),
            **kwargs,
        )


class OCPINotOwnerResponse(OCPIResponse):
    def __init__(
        self, msg: str = "Country ID and Party ID need to match your credentials."
    ):
        super().__init__(
            status_message=msg,
            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            http_status=status.HTTP_401_UNAUTHORIZED,
        )


class OCPINotFoundResponse(OCPIResponse):
    def __init__(self, msg):
        super().__init__(
            msg,
            http_status=status.HTTP_404_NOT_FOUND,
            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
        )


options_message = "Please see OPTIONS to learn what you can POST at this endpoint"


class OCPIPaginationAndHeaders(LimitOffsetPagination):
    default_limit = 50
    count = 0
    offset = 0
    limit = default_limit

    def get_paginated_response(self, data):
        headers = {
            "X-Total-Count": self.count,
            "X-Limit": self.default_limit,
        }

        next_url = self.get_next_link()
        if next_url:
            headers["Link"] = '<{next_url}>; rel="next"'.format(
                next_url=self.get_next_link()
            )

        return Response(
            OrderedDict(
                [
                    ("status_code", Ocpi.OK),
                    ("timestamp", datetime.now(pytz.utc)),
                    # .strftime(settings.OCPI_DATE_FORMAT)), if you want the date without fractions
                    ("data", data),
                ]
            ),
            headers=headers,
        )

    def paginate_queryset(self, queryset, request, view=None):
        queryset = apply_ocpi22_filters(request, queryset)
        return super().paginate_queryset(queryset, request, view)


def apply_ocpi22_filters(request, queryset) -> QuerySet:
    """
    Apply the OCPI 2.2 filters to a queryset (date range, limit, offset)
    :param request:
    :param queryset:
    :return:
    """
    date_from: str = request.GET.get("date_from")
    if date_from:
        import dateutil.parser

        date_from: datetime = dateutil.parser.parse(date_from).replace(tzinfo=pytz.UTC)
        queryset = queryset.filter(last_updated__gte=date_from)
    date_to: str = request.GET.get("date_to")
    if date_to:
        import dateutil.parser

        date_to: datetime = dateutil.parser.parse(date_to).replace(tzinfo=pytz.UTC)
        queryset = queryset.filter(last_updated__lt=date_to)

    return queryset


def generate_reference(separator: str, role: OcpiRolesEnum) -> str:
    """
    >>> len(generate_reference('-', OcpiRolesEnum.CPO)) <= settings.OCPI_22_MAX_UID_LENGTH
    True
    >>> generate_reference('-', OcpiRolesEnum.CPO) != generate_reference('-', OcpiRolesEnum.CPO)
    True
    """
    return f"{get_our_party(role)}*{separator}{uuid.uuid4().hex}"[
        : settings.OCPI_22_MAX_UID_LENGTH
    ].upper()


def generate_auth_reference():
    return generate_reference("A*", OcpiRolesEnum.EMSP)


def generate_token_id():
    return generate_reference("T*APP*", OcpiRolesEnum.EMSP)


def generate_session_uid():
    """
    Should be with the CPO identifier, since Sessions are owned by CPO
    """
    return generate_reference("S*", OcpiRolesEnum.CPO)


def generate_cdr_uid():
    """
    Should be with the CPO identifier, since CDRs are owned by CPO
    """
    return generate_reference("C*", OcpiRolesEnum.CPO)


def ocpi_credentials_request(
    url, token_base64, method, *args, timeout=20, credentials_id=None, **kwargs
):
    request_session = get_certificate_loaded_request(credentials_id)
    function = getattr(request_session, method)
    if not function:
        raise NotImplementedError(
            f"Method {method} is not supported for ocpi_credentials_request"
        )

    logger.info(f"{method.upper()} {url} with token {token_base64[:2]}****")
    headers = make_headers(
        token_base64
    )  # No routing headers for Credentials or Versions
    response = function(url, headers=headers, timeout=timeout, *args, **kwargs)
    if response.status_code not in (200, 201):
        raise OCPIProtocolError(
            f"Got OCPI response {response.status_code} for {method.upper()} {url}: {response.reason} - {response.text}",
            errno=response.status_code,
        )
    return response


def ocpi_credentials_get(*args, credentials_id=None, **kwargs):
    return ocpi_credentials_request(
        *args, credentials_id=credentials_id, method="get", **kwargs
    )


def ocpi_credentials_post(*args, credentials_id=None, **kwargs):
    return ocpi_credentials_request(
        *args, credentials_id=credentials_id, method="post", **kwargs
    )


def recursive_update_last_updated(obj):
    """Update the last_updated field of a Location, Evse or Connector
    and all its possible Evses and Connectors recursively"""
    if hasattr(obj, "last_updated"):
        obj.last_updated = datetime.now(pytz.utc)
        obj.save()
    if hasattr(obj, "evses"):
        list(
            map(
                lambda x: recursive_update_last_updated(x), (x for x in obj.evses.all())
            )
        )
    if hasattr(obj, "connectors"):
        list(
            map(
                lambda x: recursive_update_last_updated(x),
                (x for x in obj.connectors.all()),
            )
        )


class IsModificationAllowed(BasePermission):
    def has_permission(self, request, view):
        if (
            request.method in SAFE_METHODS
            or request.method == "POST"
            or request.method == "PUT"
        ):
            return True
        elif request.method == "DELETE" and request.user.is_superuser:
            return True
        return False


class HasSolidTariffDeletePermission(BasePermission):
    def has_permission(self, request, view):
        if (
            request.method in SAFE_METHODS
            or request.method == "POST"
            or request.method == "PUT"
        ):
            return True
        if request.method == "DELETE" and request.user.is_superuser:
            delete_permission = Permission.objects.filter(
                codename="delete_solidtariff"
            ).first()
            if (
                delete_permission
                and delete_permission in request.user.user_permissions.all()
            ):
                return True
        return False
