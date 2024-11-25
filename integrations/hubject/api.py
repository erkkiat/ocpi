from typing import Dict
from ninja import NinjaAPI

from integrations.hubject.services import HubjectService
from ocpi22.choices import OcpiRolesEnum
from ocpiconnector.ocpi_identities import get_our_party

api = NinjaAPI()


@api.post("/evses/full-load/", url_name="hubject-evse-full-load", response=Dict)
def update_oicp_evses_of_all_operators(request):
    service = HubjectService()
    party = get_our_party(OcpiRolesEnum.CPO)

    payload = service.get_evse_full_load_payload(party)

    if payload is None:
        return {
            "success": False,
            "message": "Operator not found",
        }

    return service.post_evse_full_load(party.__str__(), payload)
