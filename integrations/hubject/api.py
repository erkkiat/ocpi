from logging import getLogger
from typing import Dict

from custom_ninja_api import CustomNinjaAPI
from integrations.hubject.schemas import PricingProductData, ActionType
from integrations.hubject.services import HubjectService
from ocpi22.choices import OcpiRolesEnum
from ocpi22.models.tariff import SolidTariff
from ocpi22.ocpi.auth import NinjaBasicAuth
from ocpiconnector.exceptions import ConnectorTariffNotFoundError
from ocpiconnector.ocpi_identities import get_our_party, get_our_identity

logger = getLogger(__name__)

api = CustomNinjaAPI(
    auth=NinjaBasicAuth(),
    urls_namespace="hubject-api",
)
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


@api.post(
    "/evse-status/full-load/", url_name="hubject-evse-status-full-load", response=Dict
)
def start_evse_status_full_load(request) -> dict:
    party = get_our_party(OcpiRolesEnum.CPO)
    our_credentials_role = party.get_role_if_exists()
    if not our_credentials_role:
        logger.error("Cannot determine our credentials role for CPO")
        return {
            "success": False,
            "message": "Cannot determine our credentials role for CPO",
        }
    try:
        hubject_service.post_eroaming_push_evse_status(evse=None, full_load=True)
        return {"success": True, "message": "Evse status full load accepted."}
    except Exception:
        logger.exception(exc_info=True)
        return {"success": False, "message": f"No Solid Tariffs found for {str(party)}"}
