import json

from cachetools import cached
from cachetools.func import ttl_cache

import ocpi22.logging as logging
from dataclasses import dataclass, asdict
from typing import Optional, TypeAlias, Union
from urllib.parse import urljoin

import requests
from django.db.models import QuerySet
from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from rest_framework import status

from ocpi22.choices import OcpiModuleEnum, EndpointRoleEnum, OcpiRolesEnum
from ocpi22.ocpi.dataclasses import OCPIUrlComponents
from ocpi22.ocpi.headers import make_headers
from ocpi22.ocpi.parse import parse_ocpi_url
from ocpiconnector.exceptions import WrongRole

from ocpiconnector.ocpi_identities import Party
from util import OCPIVersion, reverse, with_trailing_slash, DistributedCache


@dataclass
class Route:
    url: str
    identifier: OcpiModuleEnum
    credentials_id: int
    token_base64: str
    alive: bool
    direct: bool
    version: OCPIVersion
    to: Party

    @property
    def through_hub(self) -> bool:
        return bool(not self.direct)

    def __post_init__(self):
        if self.version and isinstance(self.version, str):
            self.version = OCPIVersion(self.version)

    def __bool__(self):
        return bool(self.url and self.credentials_id)

    @property
    def credentials(self):
        from ocpi22.models.credentials import Credentials
        return Credentials.objects.get(pk=self.credentials_id)


def get_hub_credentials() -> QuerySet:
    from ocpi22.models.credentials import Credentials
    return Credentials.objects.filter(roles__role='HUB')


def find_credentials(party: Party) -> Optional['Credentials']:
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
        if not role or not role.credentials or not role.credentials.valid:
            # We may have found Credentials for a direct route, but they are not active
            return None
        return role.credentials


def find_route_from_credentials(credentials, ocpi_module: OcpiModuleEnum,
                                role: Union[str, EndpointRoleEnum] = 'RECEIVER') -> Route:
    from ocpi22.models.credentials import Endpoint
    endpoints = Endpoint.objects.filter(credentials=credentials, identifier=ocpi_module.value, role=str(role))
    endpoint_count = endpoints.count()
    if endpoint_count:
        if endpoint_count > 1:
            logging.error(f'Multiple Endpoints for {credentials.party()} in the database')
        endpoint = endpoints.first()
        return Route(url=endpoint.url, identifier=ocpi_module, credentials_id=credentials.pk,
                     token_base64=credentials.theirs_base64(), direct=True, alive=credentials.responding(),
                     version=OCPIVersion(credentials.version), to=credentials.get_party_for_role(OcpiRolesEnum.EMSP))  # Todo: How to figure out the role, or is it relevant?
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
        return Route(url=endpoint.url, identifier=ocpi_module, credentials_id=credentials.pk,
                     token_base64=credentials.theirs_base64(), direct=False, alive=credentials.responding(),
                     version=credentials.version, to=credentials.get_party_for_role(OcpiRolesEnum.HUB))
    return None


CredentialsType: TypeAlias = 'Credentials'


@DistributedCache(expiration=2*60)
def find_route(to: Union[Party, CredentialsType], ocpi_module: OcpiModuleEnum, add_path=None,
               role: EndpointRoleEnum = EndpointRoleEnum.RECEIVER) -> Optional[Route]:
    if not to:
        return None
    from ocpi22.models.credentials import Credentials
    assert isinstance(to, (Party, Credentials)), f'find_route() expected Party or Credentials, got {type(to)}'
    assert isinstance(ocpi_module, OcpiModuleEnum), f'find_route() expected OcpiModuleEnum, got {type(ocpi_module)}'
    if isinstance(to, Party):
        credentials: CredentialsType = find_credentials(to)
    else:
        credentials: CredentialsType = to

    # Todo: Consider using urllib.parse.urlparse, maybe faster

    if credentials and credentials.valid:
        # Direct route found
        route = find_route_from_credentials(credentials, ocpi_module, role=role)
    else:
        # Need a hub to route
        logging.info(f'Routing message through hub {str(to)}')
        route = find_first_hub_route(ocpi_module)  # Nothing too fancy at this point
    if route and add_path:
        # Todo: This is suboptimal for caching, do this a level before
        route.url = urljoin(f'{route.url}/', add_path)
    return route


@cached(cache={})
def get_all_command_urls() -> set:
    return {
        reverse('commands-start-session'),
        reverse('commands-stop-session'),
        reverse('commands-unlock-connector'),
        # build_absolute_uri(reverse('commands-reserve-now')),
    }


def is_a_command_url(url: str) -> bool:
    """
    Check if the provided URL contains any of the Command URLs as segments

    >>> is_a_command_url('https://example.com/ocpi/2.2.1/commands/START_SESSION/123')
    True
    >>> is_a_command_url('https://example.com/ocpi/2.2.1/commands/NOT_A_COMMAND/123')
    False
    """
    return any(map(lambda u: u in url, get_all_command_urls()))


def process_incoming_remote_command_at_hub(request: HttpRequest, data: str) -> str:
    """
    Replace any remote Command response URLs with the hub's own URLs, so that we can route the response to the MSP
    You can call this function without knowing if the request is in fact a remote command

    @param request: THe request received from MSP
    @param data: The data received from MSP
    @return: The modified data to be relayed to the CPO
    """
    from ocpi22.util import generate_random_token, command_store, build_absolute_uri
    if is_a_command_url(request.path):
        # Make sure the sender has an MSP role
        credentialsrole = request.ocpi_party
        if not credentialsrole or credentialsrole.role not in (OcpiRolesEnum.EMSP, OcpiRolesEnum.HUB):
            raise WrongRole("You need the EMSP role to be able to send remote commands.")
        # We are dealing with a Command response, so we need to replace the URL
        command_id = generate_random_token(24)  # Long enough to be unique, short enough to be usable
        json_data = json.loads(data)
        old_path = json_data.get('response_url', '')
        if old_path:
            command_response_path = reverse('commands-hubresponse', args=[command_id])
            new_path = build_absolute_uri(urljoin(with_trailing_slash(command_response_path), command_id))
            assert hasattr(request, 'credentials'), 'Unable to find credentials from request'
            credentials = request.credentials
            route_back = Route(url=old_path, identifier=OcpiModuleEnum.COMMANDS, credentials_id=credentials.pk,
                               token_base64=credentials.theirs_base64(), direct=True, alive=credentials.responding(),
                               to=credentials.get_party_for_role(OcpiRolesEnum.EMSP), version=credentials.version)
            command_store[command_id] = dict(route_back=asdict(route_back))
            new_data = data.replace(old_path, new_path)
            return new_data
    return data


def route_command_response_to_msp(ocpi_url: OCPIUrlComponents) -> Route:
    pass


def route_ocpi_request(request: HttpRequest, party: Party):
    """
    This is OCPI HUB functionality. It authorizes the incoming message and relayes it forward if it can find the
    route to the final recipient.
    """
    try:
        ocpi_url = parse_ocpi_url(request.path)
        command_response_path = '/commands/hubresponse/'  # Todo: Try to get this by using reverse()
        if command_response_path in ocpi_url.path:
            route = route_command_response_to_msp(ocpi_url)
            logging.info(f'Routing command response back to MSP party {route.to}')
            return HttpResponse(dict(status_text='ok'), status=status.HTTP_200_OK, content_type='application/json')
        else:
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

            data = getattr(request, 'body') or getattr(request, 'data')
            if data:
                if isinstance(data, bytes):
                    data = data.decode('utf-8')
                data = process_incoming_remote_command_at_hub(request, data)
                method = request.method
                url = urljoin(with_trailing_slash(route.url), ocpi_url.parameters)
                logging.info(f'Forwarding message to {str(party)} at {url}')
                response: requests.Response = requests.request(
                    method=method, url=url,
                    data=data, timeout=25,
                    headers=out_headers)
                return HttpResponse(response.text, status=response.status_code, content_type='application/json')
            else:
                return HttpResponse(dict(message_text='No data in request'), status=status.HTTP_400_BAD_REQUEST,
                                    content_type='application/json')
        if route:
            return JsonResponse({'error': f'Party {str(party)} is unreachable'},
                                status=status.HTTP_406_NOT_ACCEPTABLE)

        return JsonResponse({'error': f'Unable to find route to {str(party)}'}, status=status.HTTP_404_NOT_FOUND)

    except json.JSONDecodeError as e:
        logging.error(f'{settings.HOSTNAME}: Unable to route request: {e}')
    return JsonResponse({'error': f'Unable to route to {str(party)}'}, status=status.HTTP_406_NOT_ACCEPTABLE)
