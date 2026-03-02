import logging
from itertools import groupby
from typing import Optional

from cachetools.func import ttl_cache
from django.db.models import Prefetch, Q

from ocpi22 import choices
from util import DistributedCache


logger = logging.getLogger(__name__)


@ttl_cache(
    ttl=14400
)  # 4 hours local memory cache, maybe Redis would not be smart here since hub uses this for routing
def find_endpoints_by_roles(
    roles: Optional[tuple | list],
    ocpi_module: choices.OcpiModuleEnum,
    endpoint_role: choices.EndpointRoleEnum = choices.EndpointRoleEnum.RECEIVER.value,
    location_uid: Optional[str] = None,
) -> list:
    """
    Find all endpoints for specified roles for sending updates to other parties.
    We don't know how the receiving party handles multiple roles, so we can't really omit sending the same update
    to the same endpoint for the different roles they possess.
    """
    from ocpi22.models.credentials import CredentialsRole, Endpoint
    from ocpi22.credentials.services import CredentialsService

    result = []

    # Combine roles in a case-insensitive query
    criteria = Q()
    for r in roles:
        criteria |= Q(role__iexact=r)

    role: CredentialsRole
    for role in (
        CredentialsRole.objects.filter(criteria)
        .select_related("credentials")
        .prefetch_related("credentials__endpoints")
    ):
        credentials = role.credentials
        country_code = role.country_code
        party_id = role.party_id
        if credentials and credentials.valid:
            if location_uid and not CredentialsService.is_location_allowed(
                credentials, location_uid
            ):
                logger.info(
                    f"Skipping the endpoint for {ocpi_module} to {country_code}*{party_id} as it's not in allowed locations of credentials {credentials.id}"
                )
                continue
            result += [
                (
                    endpoint.url,
                    credentials.theirs_base64(),
                    country_code,
                    party_id,
                    credentials,
                )
                for endpoint in Endpoint.objects.filter(
                    identifier__iexact=ocpi_module.value.lower(),
                    role__iexact=endpoint_role,
                    credentials=credentials,
                )
            ]
    return result


@DistributedCache(expiration=60 * 30)  # 30 minutes cache
def get_entity_roles() -> list[list[str]]:
    """
    Get the party IDs of the entities that represent the same company

    @return: A list of lists of party IDs, which each top level list represents a company (based on Credentials)
    """
    from ocpi22.models.credentials import Credentials, CredentialsRole

    queryset = (
        Credentials.objects.prefetch_related(
            Prefetch(
                "roles",
                queryset=CredentialsRole.objects.order_by("country_code", "party_id"),
            )
        )
        .order_by("id")
        .values_list("id", "roles")
    )
    # We have now [(2, 'FI', 'CP1'), (2, 'FI', 'MSP'), (2, 'FI', 'NAP'), (3, 'FI', 'HUB'), ... ]
    # We want to group by the first element (Credentials.pk)
    result = ((a, list(b)) for a, b in groupby(queryset, lambda x: x[0]))
    # Then remove the Credentials.pk from the result since we only need the lists of party IDs
    result = [
        (a, list(map(lambda x: CredentialsRole.objects.get(pk=x[1]), b)))
        for a, b in result
    ]
    return result
