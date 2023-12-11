from functools import lru_cache
from typing import Optional

from cachetools.func import ttl_cache

from ocpi22 import choices


@ttl_cache(ttl=14400)  # 4 hours local memory cache, maybe Redis would not be smart here since hub uses this for routing
def find_endpoints_by_roles(roles: Optional[tuple], ocpi_module: choices.OcpiModuleEnum) -> list:
    """
    Find all endpoints for specified roles for sending updates to other parties.
    We don't know how the receiving party handles multiple roles, so we can't really omit sending the same update
    to the same endpoint for the different roles they possess.
    """
    from ocpi22.models.credentials import CredentialsRole, Endpoint
    result = []
    role: CredentialsRole
    for role in CredentialsRole.objects.filter(role__in=roles). \
            select_related('credentials'):
        credentials = role.credentials
        country_code = role.country_code
        party_id = role.party_id
        result += [
            (endpoint.url, credentials.theirs_base64(), country_code, party_id, credentials)
            for endpoint in Endpoint.objects.filter(
                identifier=ocpi_module.value.capitalize(),
                role=choices.EndpointRoleEnum.RECEIVER.value,
                credentials=credentials,
            ) if credentials.valid
        ]
    return result
