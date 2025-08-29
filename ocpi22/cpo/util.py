from django.core.exceptions import ValidationError

from ocpi22.choices import OcpiRolesEnum
from ocpi22.cpo.mqtt.services import ensure_db_connection
from ocpi22.models.location import Evse
from ocpiconnector.ocpi_identities import get_our_party


@ensure_db_connection
def find_our_evse(evse_uid) -> Evse:
    """
    Return our latest EVSE that matches the given UID
    This function gets expensive with a large number of EVSEs, consider simplifying the query or preloading the data
    """
    party = get_our_party(OcpiRolesEnum.CPO)
    evses = (
        Evse.objects.filter(uid__iexact=evse_uid)
        .select_related("location")
        .filter(
            location__ocpi_master__country_code__iexact=party.country_code,
            location__ocpi_master__party_id__iexact=party.party_id,
        )
        .order_by("-created")
    )
    # Todo: Check daily for overlapping Evse.uid in the background
    if not evses:
        raise ValidationError(f"EVSE {evse_uid} not found")
    return evses.first()
