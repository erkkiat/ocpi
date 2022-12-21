import json

from cachetools.func import ttl_cache

import ocpi22.logging as logging
from dataclasses import dataclass
from typing import Optional, TypeAlias, Union
from urllib.parse import urljoin

import requests
from django.db.models import QuerySet
from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from rest_framework import status

from ocpi22.choices import OcpiModuleEnum, EndpointRoleEnum
from ocpi22.ocpi.headers import make_headers
from ocpi22.ocpi.parse import parse_ocpi_url

from ocpiconnector.ocpi_identities import Party


@dataclass
class Route:
    url: str
    identifier: OcpiModuleEnum
    credentials_id: int
    token_base64: str
    alive: bool
    direct: bool
    version: str  # "22" or "221", etc.

    @property
    def through_hub(self) -> bool:
        return bool(not self.direct)

    def __bool__(self):
        return bool(self.url and self.credentials_id)


def get_hub_credentials() -> QuerySet:
    from ocpi22.models.credentials import Credentials
    return Credentials.objects.filter(roles__role='HUB')


def find_credentials(party: Party):
    from ocpi22.models.credentials import CredentialsRole
    roles = CredentialsRole.objects.filter(
        country_code=party.country_code.upper(),
        party_id=party.party_id.upper()
    ).select_related('credentials')
    roles_count = roles.count()
    if roles_count:
        # We found a direct connection
        if roles_count > 1:
            logging.error(f'{settings.HOSTNAME}: Multiple Credentials for {str(party)} in the database')
        role = roles.first()
        return role.credentials


def find_route_from_credentials(credentials, ocpi_module: OcpiModuleEnum, role: str = 'RECEIVER') -> Route:
    from ocpi22.models.credentials import Endpoint
    endpoints = Endpoint.objects.filter(credentials=credentials, identifier=ocpi_module.value, role=role)
    endpoint_count = endpoints.count()
    if endpoint_count:
        if endpoint_count > 1:
            logging.error(f'Multiple Endpoints for {credentials.party()} in the database')
        endpoint = endpoints.first()
        return Route(url=endpoint.url, identifier=ocpi_module.value, credentials_id=credentials.pk,
                     token_base64=credentials.theirs_base64(), direct=True, alive=credentials.connection_state(),
                     version=credentials.version)
    error_text = f'Endpoint `{ocpi_module.value}` not found for party {credentials}'
    logging.error(error_text)
    raise ValueError(error_text)


def find_first_hub_route(ocpi_module: OcpiModuleEnum) -> Optional[Route]:
    credentials = get_hub_credentials().first()
    if credentials:
        endpoints = credentials.endpoints.filter(credentials=credentials, identifier=ocpi_module.value,
                                                 role=EndpointRoleEnum.RECEIVER.value)
        if not endpoints.exists():
            return None
        endpoint = endpoints.first()
        return Route(url=endpoint.url, identifier=ocpi_module.value, credentials_id=credentials.pk,
                     token_base64=credentials.theirs_base64(), direct=False, alive=credentials.connection_state(),
                     version=credentials.version)
    return None


CredentialsType: TypeAlias = 'Credentials'


@ttl_cache(ttl=60 * 2)
def find_route(to: Union[Party, CredentialsType], ocpi_module: OcpiModuleEnum, add_path=None) -> Optional[Route]:
    if not to:
        return None
    if isinstance(to, Party):
        credentials: CredentialsType = find_credentials(to)
    else:
        credentials: CredentialsType = to

    # Todo: Consider using urllib.parse.urlparse, maybe faster

    if credentials:
        # Direct route found
        route = find_route_from_credentials(credentials, ocpi_module)
    else:
        # Need a hub to route
        route = find_first_hub_route(ocpi_module)  # Nothing too fancy at this point
    if route and add_path:
        # Todo: This is suboptimal for caching, do this a level before
        route.url = urljoin(f'{route.url}/', add_path)  # If URL is missing trailing slash, last component is cut off
    return route


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
                data=getattr(request, 'body') or getattr(request, 'data'), timeout=25,
                headers=out_headers)

            return HttpResponse(response.text, status=response.status_code, content_type='application/json')

        if route:
            return JsonResponse({'error': f'Party {str(party)} is unreachable'},
                                status=status.HTTP_406_NOT_ACCEPTABLE)

        return JsonResponse({'error': f'Unable to find route to {str(party)}'}, status=status.HTTP_404_NOT_FOUND)

    except json.JSONDecodeError as e:
        logging.error(f'{settings.HOSTNAME}: Unable to route request: {e}')
    return JsonResponse({'error': f'Unable to route to {str(party)}'}, status=status.HTTP_406_NOT_ACCEPTABLE)
