from ocpi22.choices import OcpiRolesEnum
from ocpi22.models.location import Evse
from ocpiconnector.ocpi_identities import get_our_party


def _find_our_evse(evse_uid) -> Evse:
    party = get_our_party(OcpiRolesEnum.CPO)
    evses = Evse.objects.filter(uid=evse_uid).select_related('location'). \
        filter(location__country_code=party.country_code, location__party_id=party.party_id)
    evse_count = evses.count()
    if not evse_count:
        raise Evse.DoesNotExist(f'EVSE with ID {evse_uid} '
                                f'does not exist in the OCPI Connector database for party {str(party)}')
    if evse_count > 1:
        raise Evse.DoesNotExist(f'There are more than one EVSE with ID {evse_uid} '
                                f'in the OCPI Connector database for party {str(party)}')
    return evses.first()
