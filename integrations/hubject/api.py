from typing import Dict
from ninja import NinjaAPI

from integrations.hubject.services import HubjectService
from ocpi22.choices import OcpiRolesEnum
from ocpiconnector.exceptions import TariffNotFoundError
from ocpiconnector.ocpi_identities import get_our_party

api = NinjaAPI()


@api.post("/evses/full-load/", url_name="hubject-evse-full-load", response=Dict)
def update_oicp_evses_by_operator(request):
    service = HubjectService()
    party = get_our_party(OcpiRolesEnum.CPO)

    try:
        payload = service.get_evse_full_load_payload(party)

        if payload is None:
            return {
                "success": False,
                "message": f"No EvseDataRecords found for operator {str(party)}",
            }

    except TariffNotFoundError:
        return {
            "success": False,
            "message": "No tariff were found for one or more of the evses.",
        }

    return service.post_evse_full_load(str(party), payload)
