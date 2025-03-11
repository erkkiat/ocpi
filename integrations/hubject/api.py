from typing import Dict
from ninja import NinjaAPI, Swagger

from integrations.hubject.schemas import PricingProductData, ActionType
from integrations.hubject.services import HubjectService
from ocpi22.choices import OcpiRolesEnum
from ocpi22.models.tariff import SolidTariff
from ocpi22.ocpi.auth import NinjaBasicAuth
from ocpiconnector.exceptions import ConnectorTariffNotFoundError
from ocpiconnector.ocpi_identities import get_our_party, get_our_identity

api = NinjaAPI(auth=NinjaBasicAuth(), docs=Swagger(), urls_namespace="hubject-api")
hubject_service = HubjectService()


@api.post("/evses/full-load/", url_name="hubject-evse-full-load", response=Dict)
def update_oicp_evses_by_operator(request):
    party = get_our_party(OcpiRolesEnum.CPO)

    try:
        payload = hubject_service.get_evse_full_load_payload(party)

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

    return hubject_service.post_evse_full_load(str(party), payload)


@api.post(
    "/pricing-products/full-load/", url_name="hubject-pricing-full-load", response=Dict
)
def start_pricing_product_full_load(request) -> dict:
    party = get_our_party(OcpiRolesEnum.CPO)
    try:
        pricing_product_data: PricingProductData = (
            hubject_service.get_all_pricing_products(party)
        )

        payload = hubject_service.get_push_pricing_product_data_payload(
            pricing_product_data, ActionType.fullLoad
        )

        return hubject_service.post_pricing_products_full_load(
            get_our_identity(OcpiRolesEnum.CPO.value), payload
        )
    except SolidTariff.DoesNotExist:
        return {"success": False, "message": f"No Solid Tariffs found for {str(party)}"}
