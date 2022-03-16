import logging
from dataclasses import dataclass
from functools import lru_cache

from django.db.models import QuerySet

from ocpi22.choices import OcpiModuleEnum


@dataclass
class Route():
    url: str
    identifier: str
    credentials_id: int
    direct: bool

    @property
    def hub(self):
        return not self.direct


def get_hub_credentials() -> QuerySet:
    # noinspection PyUnresolvedReferences
    return Credentials.objects.filter(roles__role='HUB')


def find_credentials(country_code, party_id) -> Credentials:
    # noinspection PyUnresolvedReferences
    roles = CredentialsRole.objects.filter(
        country_code=country_code.upper(),
        party_id=party_id.upper()
    ).select_related('credentials')
    roles_count = roles.count()
    if roles_count:
        # We found a direct connection
        if roles_count > 1:
            logging.error(f'Multiple Credentials for {country_code}*{party_id} in the database')
        role: CredentialsRole = roles.first()
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
    # noinspection PyUnresolvedReferences
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
