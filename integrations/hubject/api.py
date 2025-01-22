from typing import Dict
from ninja import NinjaAPI

from integrations.hubject.schemas import PricingProductData, ActionType
from integrations.hubject.services import HubjectService
from ocpi22.choices import OcpiRolesEnum
from ocpiconnector.exceptions import ConnectorTariffNotFoundError
from ocpiconnector.ocpi_identities import get_our_party, get_our_identity

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
    "/pricing-products/full-load/", url_name="hubject-pricing-full-load", response=Dict
)
def start_pricing_product_full_load(request) -> dict:
    party = get_our_party(OcpiRolesEnum.CPO)
    pricing_product_data: PricingProductData = service.get_all_pricing_products(party)

    payload = service.get_push_pricing_product_data_payload(
        pricing_product_data, ActionType.fullLoad
    )
    return service.post_pricing_products_full_load(
        get_our_identity(OcpiRolesEnum.CPO.value), payload
    )
