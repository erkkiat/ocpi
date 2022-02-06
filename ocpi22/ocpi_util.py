import json
import logging
from collections import OrderedDict
from datetime import datetime

import requests
from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.module_loading import import_string
from icecream import ic
from requests import Response
from rest_framework import exceptions, status
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response

from ocpi22.models.credentials import CredentialsRole, Endpoint
from ocpiconnector.ocpi_identities import ocpi_identities, ocpi_platform


class OcpiModule:
    ocpi_serializer_class = None
    ocpi_module_name = None
    ocpi_object_owner = None
    send_updates_to = []

    def get_party(self) -> (str, str):
        country_code = self.country_code if hasattr(self, 'country_code') else None
        party_id = self.party_id if hasattr(self, 'party_id') else None
        return country_code, party_id

    @classmethod
    def get_owner_party(cls) -> str:
        assert cls.ocpi_object_owner, \
            f'The OCPI object {cls} needs to have ocpi_object_owner specified ' \
            f'so that the sender identity is clear when sending updates to other parties.'
        # ic(cls.ocpi_object_owner, ocpi_identities.get_dict())
        return ocpi_identities.get(cls.ocpi_object_owner, default='*')

    def update_last_updated(self):
        if hasattr(self, 'last_updated'):
            if self.is_ours():
                setattr(self, 'last_updated', timezone.now())

    def atomic_post_save(self, *_args, **_kwargs) -> None:
        # ic("Generic atomic_post_save")
        # ic(args, kwargs)

        assert self.ocpi_serializer_class and self.ocpi_module_name and self.send_updates_to, \
            f'OCPI object class {type(self)} must have an ocpi_serializer_class (str), ' \
            f'ocpi_module_name (str) and send_updates_to (roles list) specified.'

        self.update_last_updated()

        if not hasattr(self, 'update_sent') and self.is_ours():
            if not hasattr(self, 'archived') or not self.archived:
                print('*** This is our object, sending updates to all known parties')
                self.send_updates()
                # Send update only once
                setattr(self, 'update_sent', True)

    def send_updates(self) -> None:
        """
        Find all endpoints interested in Tariff updates and send update in a background task.
        To disable updates, set env SEND_UPDATES to false
        """
        # Do we possess the role who controls the master data for this type of object?
        if settings.SEND_UPDATES in (True, 1, 'true', 'True'):
            if self.ocpi_object_owner not in ocpi_identities.roles:
                logging.warning(f"We don't possess the role required for sending updates for {type(self)}.")
                return
            serializer_class = self.ocpi_serializer_class

            if isinstance(serializer_class, str):
                serializer_class = import_string(serializer_class)

            serializer = serializer_class(self)
            self._send_updates(serializer.data)
        else:
            logging.warning(settings.UPDATES_DISABLED)

    @classmethod
    def _send_updates(cls, data):
        our_country_code, our_party_id = cls.get_owner_party().split('*')
        ic('Sending updates', cls, cls.send_updates_to)
        # noinspection PyUnresolvedReferences
        recipients = CredentialsRole.objects.filter(role__in=cls.send_updates_to). \
            values_list('credentials', 'country_code', 'party_id')
        # noinspection PyUnresolvedReferences
        for c, country_code, party_id in set(recipients):
            ic(c, country_code, party_id)
            # noinspection PyUnresolvedReferences
            endpoints = Endpoint.objects.filter(
                identifier=cls.ocpi_module_name,
                role=Endpoint.RECEIVER,
                credentials__id=c
            )
            e: Endpoint
            for e in endpoints:
                logging.info(f'Send update to {cls.ocpi_module_name} module at {e.url}')
                from ocpi22.tasks import send_update
                parameters = data, e.url, e.get_token_base64(), country_code, party_id, \
                             our_country_code, our_party_id
                if settings.BACKGROUND_SEND in (True, 1, 'True', 'true'):
                    ic()
                    send_update.delay(*parameters)
                else:
                    ic()
                    send_update(*parameters)

    @classmethod
    def send_hub_updates(cls, data) -> None:
        ic()
        if ocpi_platform.is_hub and settings.SEND_UPDATES in (True, 1, 'true', 'True'):
            print(f'Sending HUB updates for {cls}.')
            ic(data)
            cls._send_updates(data)


def ocpi_post(url, token_base64, *args, **kwargs) -> Response:
    print(f'Posting to {url}')
    data = ''
    if 'data' in kwargs:
        data = json.dumps(kwargs.pop('data'))
        # ic(data)
    response = requests.post(url, *args, **kwargs, data=data,
                             headers={
                                 "Authorization": f'Token {token_base64}',
                                 'content-type': 'application/json',
                             })
    if response.status_code >= 300:
        print(f'*** Got response: {response.status_code} - {response.reason}')
        logging.error(response.text)
        raise exceptions.APIException(f'Got response for {url}: {response.status_code} - {response.reason} ')
    return response


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
            logging.error(status_message)
        result = dict(
            status_code=status_code,
            status_message=status_message,
            timestamp=timezone.now(),
            data=data
        )
        super().__init__(result, status=http_status, *args, **kwargs)


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
            http_status=status.HTTP_403_FORBIDDEN)


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

    STANDARD_CHOICES = (
        ('IEC_62196_T2', 'Type 2 "Mennekes"'),
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

    CURRENCY_CHOICES = (
        ('EUR', 'Euro'),
        ('ALL', 'Albanian lek'),
        ('BYN', 'Belarusian ruble'),
        ('BAM', 'Bosnia and Herzegovina convertible mark'),
        ('BGN', 'Bulgarian lev'),
        ('HRK', 'Croatian kuna'),
        ('CZK', 'Czech koruna'),
        ('DKK', 'Danish krone'),
        ('ISK', 'Icelandic króna'),
        ('HUF', 'Hungarian forint'),
        ('MDL', 'Moldovan leu'),
        ('NOK', 'Norwegian krone'),
        ('PLN', 'Polish złoty'),
        ('GBP', 'Pound sterling'),
        ('RON', 'Romanian leu'),
        ('RUB', 'Russian ruble'),
        ('MKD', 'Second Macedonian denar'),
        ('RSD', 'Serbian dinar'),
        ('SEK', 'Swedish krona'),
        ('CHF', 'Swiss franc'),
        ('TRY', 'Turkish lira'),
        ('UAH', 'Ukrainian hryvnia'),
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
            ('timestamp', timezone.now()),
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
