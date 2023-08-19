from cachetools import cached
from cachetools.keys import hashkey
from icecream import ic

from ocpi22.models.credentials import CredentialsRole
from ocpi22.ocpi.util_party import get_sender_party
from ocpiconnector.ocpi_identities import Party

partners_cache = dict()


@cached(cache=partners_cache)
def get_partners_by_party(party: Party) -> set[int]:
    print('***** Fetching partners for', party)
    role = CredentialsRole.objects.get(country_code__iexact=party.country_code, party_id__iexact=party.party_id)
    ic(role, role.agreed_parties.all())
    partners = role.agreed_parties.all().values_list('id', flat=True)
    ic(partners)
    return set(partners)


def get_partners(request) -> set[int]:
    if request and hasattr(request, 'headers'):
        party = get_sender_party(request.headers)
        return get_partners_by_party(party)
    return set()


def invalidate_partner_cache(party: Party) -> bool:
    key_to_invalidate = hashkey(party)
    return bool(partners_cache.pop(key_to_invalidate, None))


# You can test this with:
#
# curl -X GET \
#      -H "Authorization: Token <put the theirs_base64 token here> \
#      -H "Accept: application/json; indent=4" -H "Ocpi-From-Country-Code: FI" -H "Ocpi-From-Party-Id: 000" \
#      http://localhost:8001/ocpi/2.2.1/hubclientinfo
#
