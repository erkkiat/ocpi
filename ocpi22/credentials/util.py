from functools import lru_cache
from typing import Optional

from ocpi22 import choices


@lru_cache(maxsize=None)
def find_endpoints_by_roles(roles: Optional[tuple], ocpi_module: choices.OcpiModuleEnum) -> list:
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
