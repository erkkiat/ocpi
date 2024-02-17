import os

import cachetools

from django.http import HttpRequest

from ocpi22.ocpi.util_party import get_sender_party
from ocpiconnector.ocpi_identities import Party, ocpi_identities


partners_cache = cachetools.TTLCache(maxsize=1024, ttl=60*60*4)


@cachetools.cached(cache=partners_cache)
def get_partners_by_party(party: Party, source: dict = os.environ) -> set[int]:
    """
    Get the partners of a party from the database. If the party is not found in the database, it is created.
    This function returns a set of primary keys of the partners of the given party, because that is used
    for filtering OCPI objects depending on which party is asking.
    @param party: The asking party
    @param source: Source of the environment variables (for unit testing purposes)
    @return: A set of CredentialsRole primary keys
    """
    from ocpi22.models.credentials import CredentialsRole
    from ocpi22.models.business_details import BusinessDetails
    if not party:
        return set()
    print('***** Checking partners for', party)
    try:
        role = CredentialsRole.objects.get(country_code__iexact=party.country_code, party_id__iexact=party.party_id)
    except CredentialsRole.DoesNotExist:
        # Our own role is missing, we need to create it
        if str(party) in ocpi_identities:
            business_name = source.get('BUSINESS_NAME', 'N/A')
            website = source.get('BUSINESS_WEBSITE', '')
            bt, _created = BusinessDetails.objects.get_or_create(name=business_name, website=website)
            role = CredentialsRole.objects.create(country_code=party.country_code, party_id=party.party_id,
                                                  business_details=bt)
        else:
            raise
    our_partners = role.agreed_parties.all().values_list('id', flat=True)
    we_are_partners_to = role.agreed_parties_backwards.all().values_list('id', flat=True)
    return set.union(set(our_partners), set(we_are_partners_to))


def get_partners_by_party_as_party(party: Party) -> set[Party]:
    primary_keys = get_partners_by_party(party)
    from ocpi22.models.credentials import CredentialsRole
    roles = CredentialsRole.objects.filter(pk__in=primary_keys)
    return set(role.party for role in roles)


def get_partners(request: HttpRequest) -> set[int]:
    if request and hasattr(request, 'headers'):
        party = get_sender_party(request.headers)
        return get_partners_by_party(party)
    return set()


def add_partner(party: Party, partner: Party) -> bool:
    role = party.get_role_if_exists()
    partner_role = partner.get_role_if_exists()
    if all([role, partner_role]):
        role.agreed_parties.add(partner_role)
        invalidate_partner_cache(party)
        invalidate_partner_cache(partner)
        return True
    raise ValueError(f'Parties {party} and {partner} are not both found in the database')


def remove_partner(party: Party, partner: Party) -> bool:
    role = party.get_role_if_exists()
    partner_role = partner.get_role_if_exists()
    if all([role, partner_role]):
        role.agreed_parties.remove(partner_role)
        invalidate_partner_cache(party)
        invalidate_partner_cache(partner)
        return True
    raise ValueError(f'Parties {party} and {partner} are not both found in the database')


def invalidate_partner_cache(party: Party) -> bool:
    partners_cache.clear()
    return True

    # Todo: Invalidate a single Party from cache, but the calling code is not yet working properly
    # from ocpi22 import logging
    # key_to_invalidate = hashkey(party)
    # result = bool(partners_cache.pop(key_to_invalidate, None))
    # logging.info(f'Invalidated partner cache for {party}: {result}')
    # return result


# You can test this with:
#
# curl -X GET \
#      -H "Authorization: Token <put the theirs_base64 token here> \
#      -H "Accept: application/json; indent=4" -H "Ocpi-From-Country-Code: FI" -H "Ocpi-From-Party-Id: 000" \
#      http://localhost:8001/ocpi/2.2.1/hubclientinfo
#
