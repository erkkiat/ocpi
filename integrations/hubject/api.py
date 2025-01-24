from typing import Dict
from ninja import NinjaAPI

from integrations.hubject.services import HubjectService
from ocpi22.choices import OcpiRolesEnum
from ocpiconnector.exceptions import ConnectorTariffNotFoundError
from ocpiconnector.ocpi_identities import get_our_party

api = NinjaAPI()
service = HubjectService()


@api.post("/evses/full-load/", url_name="hubject-evse-full-load", response=Dict)
def update_oicp_evses_by_operator(request):
    party = get_our_party(OcpiRolesEnum.CPO)

    try:
        payload = service.get_evse_full_load_payload(party)

        if payload is None:
            return {
                "success": False,
                "message": f"No EvseDataRecords found for operator {str(party)}",
            }

    except ConnectorTariffNotFoundError:
        return {
            "success": False,
            "message": "No tariff were found for one or more of the evses.",
        }

    return service.post_evse_full_load(str(party), payload)


@api.post(
    "/evse-pricing-products/full-load/",
    url_name="hubject-evse-pricing-full-load",
    response=Dict,
)
def map_evses_and_pricing_products(request) -> Dict:
    party = get_our_party(OcpiRolesEnum.CPO)
    evse_product_id_provider_id_map = service.get_evse_product_provider_maps(party)

    payload = service.get_evse_pricing_product_data_full_load_payload(
        evse_product_id_provider_id_map
    )
    if len(payload.EVSEPricing) == 0:
        return {"status_message": "EvsePricing cannot be empty."}
    return service.post_evse_pricing_item_full_load(str(get_our_party()), payload)
