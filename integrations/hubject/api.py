import json
from typing import Dict

from pydantic.v1 import ValidationError

from custom_ninja_api import CustomNinjaAPI
from integrations.hubject.schemas import (
    PricingProductData,
    ActionType,
    HubjectCDRError,
    ERoamingAuthorizeRemoteStart,
    ERoamingAcknowledgment,
    Identification,
    RemoteIdentification,
    StatusCode,
)
from integrations.hubject.services import HubjectService
from ocpi22.choices import OcpiRolesEnum
from ocpi22.models.tariff import SolidTariff
from ocpi22.ocpi.auth import NinjaBasicAuth, HubjectCertAuth
from ocpiconnector.exceptions import ConnectorTariffNotFoundError
from ocpiconnector.ocpi_identities import get_our_party, get_our_identity

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
    "/cdr/",
    url_name="hubject-cdr",
    response={
        200: dict,
        400: HubjectCDRError,
        503: HubjectCDRError,
    },
)
def send_charge_detail_record(request, session_id: str):
    if not session_id or not session_id.strip():
        return 400, HubjectCDRError(
            success=False,
            errorType="Invalid Input",
            error="session_id cannot be blank or empty",
        )

    result = HubjectService.post_eroaming_charge_detail_record(
        get_our_identity(OcpiRolesEnum.CPO.value),
        cdr=None,
        session_id=session_id,
        retries=0,
    )

    if not result.get("success", False) and result.get("errorType") == "Invalid Input":
        return 400, HubjectCDRError(**result)
    elif (
        not result.get("success", False)
        and result.get("errorType") == "Hubject server Error"
        or result.get("errorType") == "HTTP Error"
    ):
        return 503, HubjectCDRError(**result)
    else:
        return 200, result


@api.post(
    "/remote/start/api/oicp/charging/v21/providers/DE*ICE/authorize-remote/start",
    url_name="hubject-remote-start",
    auth=HubjectCertAuth(),
    response={
        200: ERoamingAcknowledgment,
        400: HubjectCDRError,
        503: HubjectCDRError,
    },
)
def receive_remote_start_command(request):
    try:
        remote_start_command = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return 400, ERoamingAcknowledgment(
            result=False,
            status_code=StatusCode("022"),
            session_id="",
            cpo_partner_session_id="",
            emp_partner_session_id="",
        )

    try:
        command = ERoamingAuthorizeRemoteStart(
            session_id=remote_start_command.get("SessionID"),
            cpo_partner_session_id=remote_start_command.get("CPOPartnerSessionID"),
            emp_partner_session_id=remote_start_command.get("EMPPartnerSessionID"),
            provider_id=remote_start_command.get("ProviderID"),
            evse_id=remote_start_command.get("EvseID"),
            identification=Identification(
                RFIDIdentification=None,
                RFIDMifareFamilyIdentification=None,
                RemoteIdentification=RemoteIdentification(
                    EvcoID=remote_start_command.get("Identification", {})
                    .get("RemoteIdentification", {})
                    .get("EvcoID"),
                ),
                QRCodeIdentification=None,
                PlugAndChargeIdentification=None,
            ),
            partner_product_id=remote_start_command.get("PartnerProductID"),
        )
    except ValidationError:
        return 400, ERoamingAcknowledgment(
            result=False,
            status_code=StatusCode("022"),
            session_id=remote_start_command.get("SessionID"),
            cpo_partner_session_id=remote_start_command.get("CPOPartnerSessionID"),
            emp_partner_session_id=remote_start_command.get("EMPPartnerSessionID"),
        )
    result = hubject_service.process_remote_start_command(command)
    return 200, result
