import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urljoin

import requests
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, JsonResponse
from rest_framework import status

from ocpi22.choices import OcpiModuleEnum, EndpointRoleEnum
from ocpi22.ocpi_util import parse_ocpi_url, make_headers

from ocpiconnector.ocpi_identities import Party


@dataclass
class Route:
    url: str
    identifier: OcpiModuleEnum
    credentials_id: int
    token_base64: str
    alive: bool
    direct: bool

    @property
    def through_hub(self):
        return not self.direct

    def __bool__(self):
        return self.url and self.alive


def get_hub_credentials() -> QuerySet:
    from ocpi22.models.credentials import Credentials
    # noinspection PyUnresolvedReferences
    return Credentials.objects.filter(roles__role='HUB')


def find_credentials(party: Party):
    from ocpi22.models.credentials import CredentialsRole
    # noinspection PyUnresolvedReferences
    roles = CredentialsRole.objects.filter(
        country_code=party.country_code.upper(),
        party_id=party.party_id.upper()
    ).select_related('credentials')
    roles_count = roles.count()
    if roles_count:
        # We found a direct connection
        if roles_count > 1:
            logging.error(f'Multiple Credentials for {str(party)} in the database')
        role = roles.first()
        return role.credentials


def find_route_from_credentials(credentials, ocpi_module: OcpiModuleEnum, role: str = 'RECEIVER') -> Route:
    from ocpi22.models.credentials import Endpoint
    # noinspection PyUnresolvedReferences
    endpoints = Endpoint.objects.filter(credentials=credentials, identifier=ocpi_module.value, role=role)
    endpoint_count = endpoints.count()
    if endpoint_count:
        if endpoint_count > 1:
            logging.error(f'Multiple Endpoints for {credentials.party()} in the database')
        endpoint = endpoints.first()
        return Route(url=endpoint.url, identifier=ocpi_module.value, credentials_id=credentials.pk,
                     token_base64=credentials.theirs_base64(), direct=True, alive=credentials.connection_state())
    error_text = f'Endpoint {ocpi_module.value} not found for {credentials}'
    logging.error(error_text)
    raise ValueError(error_text)


def find_first_hub_route(ocpi_module: OcpiModuleEnum) -> Route:
    credentials = get_hub_credentials().first()
    endpoints = credentials.endpoints.filter(credentials=credentials, identifier=ocpi_module.value,
                                             role=EndpointRoleEnum.RECEIVER.value)
    endpoint = endpoints.first()
    return Route(url=endpoint.url, identifier=ocpi_module.value, credentials_id=credentials.pk,
                 token_base64=credentials.theirs_base64(), direct=False, alive=credentials.connection_state())


@lru_cache(maxsize=None)
def find_route(party: Party, ocpi_module: OcpiModuleEnum) -> Route:
    credentials = find_credentials(party)
    if credentials:
        # Direct route found
        return find_route_from_credentials(credentials, ocpi_module)
    else:
        # Need a hub to route
        return find_first_hub_route(ocpi_module)  # Nothing too fancy at this point


def route_ocpi_request(request: HttpRequest, party: Party):
    """
    This is OCPI HUB functionality. It authorizes the incoming message and relayes it forward if it can find the
    route to the final recipient.
    """
    try:
        ocpi_url = parse_ocpi_url(request.path)
        logging.info(f'Routing to {party}, module {ocpi_url}')
        route = find_route(party, ocpi_url.module)
        if route and hasattr(request, 'body') and hasattr(request, 'headers'):
            # Pick the OCPI related incoming headers
            ocpi_keys = dict((key, value) for key, value in request.META.items() if 'ocpi' in key.lower())

            # Include all of them in outgoing headers
            out_headers = make_headers(
                route.token_base64,
                extra=ocpi_keys
            )

            logging.info(f'Forwarding message to {str(party)}')

            response: requests.Response = requests.request(
                method=request.method, url=urljoin(f'{route.url}/', ocpi_url.parameters),
                data=getattr(request, 'body') or getattr(request, 'data'),
                headers=out_headers)

            return HttpResponse(response.text, status=response.status_code, content_type='application/json')

        if not route.alive:
            return JsonResponse({'error': f'Party {str(party)} is currently offline'},
                                status=status.HTTP_406_NOT_ACCEPTABLE)

        return JsonResponse({'error': f'Unable to find route to {str(party)}'}, status=status.HTTP_404_NOT_FOUND)

    except json.JSONDecodeError as e:
        print(f'Unable to route request: {e}')
    return JsonResponse({'error': f'Unable to route to {str(party)}'}, status=status.HTTP_406_NOT_ACCEPTABLE)
