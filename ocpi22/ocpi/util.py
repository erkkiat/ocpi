import logging
import uuid
from collections import OrderedDict
from datetime import datetime
from functools import lru_cache

import requests
from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.module_loading import import_string
from requests import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from ocpi22.choices import OcpiRolesEnum
from rest_framework.response import Response

from ocpi22.ocpi.headers import make_headers
from ocpi22.routing import find_route
from ocpi22.logging import log_error
from ocpiconnector.ocpi_identities import ocpi_identities, ocpi_platform, get_identity, Party, get_our_party


class OcpiModule:
    # The serializer class to use when sending updates to other OCPI parties
    ocpi_serializer_class = None

    # The module name to be used when looking for endpoints to send updates to
    ocpi_module_name = None

    # This determines which identity of ours we will use when sending updates for this type of object
    ocpi_object_owner = None

    # A list of roles to receive updates on this type of objects
    # If you set this to INTERESTED_PARTIES, updates will only be sent to the party which is billed for the transaction
    send_updates_to = []

    INTERESTED_PARTIES = -1

    def get_party(self) -> (str, str):
        country_code = self.country_code if hasattr(self, 'country_code') else None
        party_id = self.party_id if hasattr(self, 'party_id') else None
        return country_code, party_id

    @classmethod
    def get_owner_identity(cls) -> str:
        if ocpi_platform.is_hub:
            return get_identity('HUB')

        assert hasattr(cls, 'ocpi_object_owner'), \
            f'The OCPI object {cls} needs to have ocpi_object_owner specified ' \
            f'so that the sender identity is clear when sending updates to other parties.'
        # ic(cls.ocpi_object_owner, ocpi_identities.get_dict())
        return ocpi_identities.get(cls.ocpi_object_owner, default='*')

    def update_last_updated(self):
        if hasattr(self, 'last_updated'):
            if self.is_ours():
                setattr(self, 'last_updated', timezone.now())

    def atomic_post_save(self, *_args, **_kwargs) -> None:
        assert hasattr(self, 'ocpi_serializer_class') and hasattr(self, 'ocpi_module_name') \
               and hasattr(self, 'send_updates_to'), \
            f'OCPI object class {type(self)} must have an ocpi_serializer_class (str), ' \
            f'ocpi_module_name (str) and send_updates_to (roles list) specified.'

        self.update_last_updated()

        if not hasattr(self, 'update_sent') and self.is_ours():
            if not hasattr(self, 'archived') or not self.archived:
                self.send_updates()
                # Send update only once
                setattr(self, 'update_sent', True)

    def send_updates(self, data=None, method='put', path_components=None) -> None:
        """
        Find all endpoints interested in OCPI object updates and send update in a background task.
        To disable updates, set env SEND_UPDATES to false
        """
        if settings.SEND_UPDATES in (True, 1, 'true', 'True'):
            # Do we possess the role who controls the master data for this type of object or are we acting as HUB
            if self.ocpi_object_owner not in ocpi_identities.roles and not ocpi_platform.is_hub:
                logging.warning(f"We don't possess the role required for sending updates for {type(self)}.")
                return

            if not data:
                serializer_class = self.ocpi_serializer_class

                if isinstance(serializer_class, str):
                    serializer_class = import_string(serializer_class)

                serializer = serializer_class(self)
                data = serializer.data

            if self.send_updates_to == OcpiModule.INTERESTED_PARTIES:
                logging.info('Sending updates to INTERESTED PARTIES')
                self.send_update_to_interested_parties(data, method, path_components)
            else:
                logging.info('Sending updates to ALL connected parties')
                self._send_updates(data, method)
        else:
            logging.warning(settings.UPDATES_DISABLED)

    @classmethod
    def _send_updates(cls, data, method='put', path_components=None) -> bool:
        from ocpi22.models.credentials import find_endpoints_by_roles
        our_country_code, our_party_id = cls.get_owner_identity().split('*')
        uid = data.get('uid', data.get('id', 'N/A'))
        logging.info(
            f'Sending updates for {cls} {uid} from {our_country_code}*{our_party_id} to {cls.send_updates_to}'
        )

        # Todo: Speed would be increased by removing dynamic imports => get endpoints from Redis or cache them

        if isinstance(cls.send_updates_to, tuple):
            for url, token_base64, country_code, party_id in find_endpoints_by_roles(
                    cls.send_updates_to, cls.ocpi_module_name):
                if path_components:
                    url = f'{url}/{"/".join(path_components)}'
                cls._send_update(data, url, token_base64, to=Party(country_code, party_id),
                                 sender=Party(our_country_code, our_party_id), method=method)
            return True
        logging.error(f"{settings.HOSTNAME}: Unable to send updates for {cls}, don't know where to send.")
        return False

    @classmethod
    def _send_update(cls, data: dict, url, token_base64, to: Party, sender: Party, method='put'):
        # ic()
        # ic(e, country_code, party_id, our_country_code, our_party_id)
        if url and token_base64 and to and sender:
            logging.info(f'Send update {cls.ocpi_module_name.value}@{str(to)}, url {url}')
            from ocpi22.tasks import send_ocpi_request
            args = data, url, token_base64, to.country_code, to.party_id, \
                   sender.country_code, sender.party_id, method
            if settings.BACKGROUND_SEND in (True, 1, 'True', 'true'):
                send_ocpi_request.apply_async(args, retry=False)
            else:
                send_ocpi_request(*args)
        else:
            logging.warning(f"Skipping send for {cls}")

    @classmethod
    def send_hub_updates(cls, data) -> None:
        if ocpi_platform.is_hub and settings.SEND_UPDATES in (True, 1, 'true', 'True'):
            logging.info(f'Sending HUB updates for {cls}.')
            # ic(data)
            cls._send_updates(data)

    def send_update_to_interested_parties(self, data, method='put', path_components=None):
        if hasattr(self, 'credentials'):

            if not hasattr(self, 'billed_to'):
                log_error(f'Object #{self.uid} - {self} has no billed_to')
                return

            to = Party(*(self.billed_to.split('*')))
            sender = Party(*(self.get_owner_identity().split('*')))
            route = find_route(to, self.ocpi_module_name,
                               add_path="/".join(path_components) if path_components else None)
            if route:
                self._send_update(data, route.url, route.token_base64, to=to, sender=sender, method=method)
            else:
                logging.error(f'{settings.HOSTNAME}: Unable to find route to {str(to)}')


def ocpi_post(url, token_base64,
              to: Party,
              sender: Party,
              *args, **kwargs) -> Response:
    logging.info(f'Posting to {url}')
    data = ''
    if 'data' in kwargs:
        data = kwargs.pop('data')
        # ic(data)
    response = requests.post(url, *args, **kwargs, json=data,
                             headers=make_headers(token_base64, to, sender))
    if response.status_code >= 300:
        try:
            data = response.json()
            logging.error(f'{settings.HOSTNAME}: `{url}` - {response.status_code} - {data}')
            # raise ValidationError(data.get("status_message") or f'Unknown error: {data}')
        except (Exception, requests.exceptions.JSONDecodeError) as e:
            logging.error(f'{settings.HOSTNAME}: `{url}` - {response.status_code} - {e}')
    return response


def format_ocpi_response(status_code: int = 1000, status_message: str = '', data='') -> dict:
    return dict(
        status_code=status_code,
        status_message=status_message,
        timestamp=timezone.now(),  # .strftime("%Y-%m-%dT%H:%M:%SZ"),
        data=data
    )


class OCPIResponse(Response):
    def __init__(self, data='', status_code=1000, status_message='', http_status=status.HTTP_200_OK, errors=None,
                 *args, **kwargs):
        if isinstance(status_message, list):
            status_message = ', '.join([s for s in status_message])
        if isinstance(errors, dict):
            status_message = ', '.join([f"{field}: {error}" for field, error in errors.items()])
            data = errors  # This is a courtacy, it's not OCPI compliant
            status_code = Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS
            http_status = status.HTTP_400_BAD_REQUEST
            logging.error(f'{settings.HOSTNAME}: {status_message}')
        result = format_ocpi_response(status_code, status_message, data)
        super().__init__(result, status=kwargs.pop('status', http_status), *args, **kwargs)


class OCPIBadRequestResponse(OCPIResponse):
    def __init__(self):
        super().__init__(
            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            http_status=status.HTTP_400_BAD_REQUEST)


class NotOwner(OCPIResponse):
    def __init__(self):
        super().__init__(
            status_message="Country ID and Party ID need to match your credentials.",
            status_code=2002,
            http_status=status.HTTP_401_UNAUTHORIZED)


class Ocpi:
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
        LOCATIONS = 'locations'
        TARIFFS = 'tariffs'
        TOKENS = 'tokens'
        CREDENTIALS = 'credentials'
        SESSIONS = 'sessions'
        CDRS = 'cdrs'
        COMMANDS = 'commands'
        CLIENTINFO = 'hubclientinfo'

    STANDARD_CHOICES = (
        ('IEC_62196_T2', 'Type 2'),
        ('IEC_62196_T2_COMBO', 'CCS type 2'),
        ('CHADEMO', 'CHAdeMO'),
        ('IEC_62196_T1', 'IEC 62196 Type 1 "SAE J1772"'),
        ('IEC_62196_T1_COMBO', 'CCS type 1'),
        ('IEC_62196_T3A', 'IEC 62196 Type 3A'),
        ('IEC_62196_T3C', 'IEC 62196 Type 3C "Scame"'),
        ('DOMESTIC_A', 'Type "A", NEMA 1-15, 2 pins'),
        ('DOMESTIC_B', 'Type "B", NEMA 5-15, 3 pins'),
        ('DOMESTIC_C', 'Type "C", CEE 7 / 17, 2 pins'),
        ('DOMESTIC_D', 'Type "D", 3 pin'),
        ('DOMESTIC_E', 'Type "E", CEE 7 / 5 3 pins'),
        ('DOMESTIC_F', 'Type "F", CEE 7 / 4, Schuko, 3 pins'),
        ('DOMESTIC_G', 'Type "G", BS 1363, Commonwealth, 3 pins'),
        ('DOMESTIC_H', 'Type "H", SI-32, 3 pins'),
        ('DOMESTIC_I', 'Type "I", AS 3112, 3 pins'),
        ('DOMESTIC_J', 'Type "J", SEV 1011, 3 pins'),
        ('DOMESTIC_K', 'Type "K", DS 60884-2-D1, 3 pins'),
        ('DOMESTIC_L', 'Type "L", CEI 23-16-VII, 3 pins'),
        ('IEC_60309_2_single_16', 'IEC 60309-2 single phase 16 A (blue)'),
        ('IEC_60309_2_three_16', 'IEC 60309-2 three phase 16 A (red)'),
        ('IEC_60309_2_three_32', 'IEC 60309-2 three phase 32 A (red)'),
        ('IEC_60309_2_three_64', 'IEC 60309-2 three phase 64 A (red)'),
        ('PANTOGRAPH_BOTTOM_UP', 'On-board Bottom-up-Pantograph'),
        ('PANTOGRAPH_TOP_DOWN', 'Off-board Top-down-Pantograph'),
        ('TESLA_R', 'Tesla "Roadster"-type'),
        ('TESLA_S', 'Tesla "Model-S"-type'),
    )

    FORMAT_CHOICES = (
        ('SOCKET', 'Socket'),
        ('CABLE', 'Cable'),
    )

    POWERTYPES = dict(
        CHADEMO='DC',
        IEC_62196_T2_COMBO='DC',
        IEC_62196_T2='AC_3_PHASE'
    )

    POWERTYPE_CHOICES = (
        ('AC_1_PHASE', 'AC 1-phase'),
        ('AC_3_PHASE', 'AC 3-phase'),
        ('DC', 'DC')
    )


class OCPIPaginationAndHeaders(LimitOffsetPagination):
    default_limit = 100

    def get_paginated_response(self, data):
        headers = {
            'X-Total-Count': self.count,
            'X-Limit': self.default_limit,
        }

        next_url = self.get_next_link()
        if next_url:
            headers['Link'] = '<{next_url}; rel="next">'.format(next_url=self.get_next_link())

        return Response(OrderedDict([
            ('status_code', 1000),
            ('timestamp', timezone.now()),  # .strftime("%Y-%m-%dT%H:%M:%SZ")), if you want the date without fractions
            ('data', data),
        ]), headers=headers)

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
    date_from: str = request.GET.get('date_from')
    if date_from:
        import dateutil.parser
        date_from: datetime = dateutil.parser.parse(date_from, ignoretz=True)
        queryset = queryset.filter(last_updated__gte=date_from)
    date_to: str = request.GET.get('date_to')
    if date_to:
        import dateutil.parser
        date_to: datetime = dateutil.parser.parse(date_to, ignoretz=True)
        queryset = queryset.filter(last_updated__lt=date_to)
    return queryset


def dict_keys_to_lower_and_filter(d: dict, filter_word: str) -> dict:
    """
    >>> dict_keys_to_lower_and_filter({'OCPI-this': 'that', 'ocpi-THAT': 'THIS', 'others': 'ignored'}, 'ocpi')
    {'ocpi-this': 'that', 'ocpi-that': 'THIS'}
    """
    return dict((key.lower(), value) for key, value in d.items() if filter_word in key.lower())


@lru_cache(maxsize=None)
def _secondary_header_name(header_name: str) -> str:
    """
    >>> _secondary_header_name('HTTP_OCPI_FROM_COUNTRY_CODE')
    'ocpi-from-country-code'
    >>> _secondary_header_name('http_ocpi_to_party_id')
    'ocpi-to-party-id'
    """
    return header_name.replace('_', '-').lower().replace('http-', '')


def get_sender_party(headers,
                     country_code_key='HTTP_OCPI_FROM_COUNTRY_CODE',
                     party_id_key='HTTP_OCPI_FROM_PARTY_ID'
                     ) -> Party:
    """
    >>> get_sender_party({'Ocpi-From-Country-Code': 'FI', 'Ocpi-From-Party-Id': 'EON'})
    Party(country_code='FI', party_id='EON')
    >>> get_sender_party({'HTTP_OCPI_FROM_COUNTRY_CODE': 'FI', 'HTTP_OCPI_FROM_PARTY_ID': 'EON'})
    Party(country_code='FI', party_id='EON')
    >>> get_sender_party({'ocpi-from-country-code': 'fi', 'ocpi-from-party-id': 'eon'})
    Party(country_code='FI', party_id='EON')
    >>> str(get_sender_party({'Ocpi-From-Country-Code': 'FI', 'Ocpi-From-Party-Id': 'EON'}))
    'FI*EON'
    """
    headers = dict_keys_to_lower_and_filter(headers, 'ocpi')
    country_code = headers.get(country_code_key.lower(),
                               headers.get(_secondary_header_name(country_code_key), '')).upper()
    party_id = headers.get(party_id_key.lower(),
                           headers.get(_secondary_header_name(party_id_key), '')).upper()
    return Party(country_code, party_id)


def get_to_party(headers) -> Party:
    """
    >>> get_to_party({'Ocpi-To-Country-Code': 'FI', 'Ocpi-To-Party-Id': 'EON'})
    Party(country_code='FI', party_id='EON')
    >>> get_to_party({'HTTP_OCPI_TO_COUNTRY_CODE': 'FI', 'HTTP_OCPI_TO_PARTY_ID': 'EON'})
    Party(country_code='FI', party_id='EON')
    """
    return get_sender_party(headers, 'HTTP_OCPI_TO_COUNTRY_CODE', 'HTTP_OCPI_TO_PARTY_ID')


def generate_reference(separator: str, role: OcpiRolesEnum) -> str:
    """
    >>> len(generate_reference('-', OcpiRolesEnum.CPO)) <= 36
    True
    >>> generate_reference('-', OcpiRolesEnum.CPO) != generate_reference('-', OcpiRolesEnum.CPO)
    True
    """
    return f'{get_our_party(role)}*{separator}{uuid.uuid4().hex}'[:36].upper()


def generate_auth_reference():
    return generate_reference('A*', OcpiRolesEnum.EMSP)


def generate_token_id():
    return generate_reference('T*APP*', OcpiRolesEnum.EMSP)


def generate_session_uid():
    """
    Should be with the CPO identifier, since Sessions are owned by CPO
    """
    return generate_reference('S*', OcpiRolesEnum.CPO)


def generate_cdr_uid():
    """
    Should be with the CPO identifier, since CDRs are owned by CPO
    """
    return generate_reference('C*', OcpiRolesEnum.CPO)
