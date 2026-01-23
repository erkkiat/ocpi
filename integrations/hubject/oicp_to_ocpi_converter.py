import logging
from datetime import datetime

import pytz
from django.conf import settings

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def map_successful_oicp_authorization_response_to_ocpi_221(
    oicp_response: dict | None, token_id: str
) -> dict | None:
    from integrations.hubject.services import HubjectService

    if not oicp_response:
        return None
    authorization_status = oicp_response.get("AuthorizationStatus")
    try:
        country_code, party_id = HubjectService.decode_country_code_and_party_id(
            oicp_response.get("ProviderID")
        )
    except ValueError as e:
        logger.error(
            "Failed to decode country code and party ID from ProviderID.",
            extra={"ProviderID": oicp_response.get("ProviderID"), "error": str(e)},
        )
        return None

    authorization_reference = oicp_response["SessionID"]

    if authorization_status and country_code and party_id:
        data = {
            "allowed": {"Authorized": "ALLOWED"}.get(
                authorization_status, "NOT_ALLOWED"
            ),
            "authorization_reference": authorization_reference,
            "hub_session_id": oicp_response["SessionID"],
            "responding_party": settings.HUBJECT_OPERATOR_ID,
            "token": {
                "contract_id": "N/A",
                "country_code": country_code,
                "party_id": party_id,
                "default_profile_type": "REGULAR",
                "issuer": f"{country_code}*{party_id}",
                "language": settings.LANGUAGE_CODE.upper(),
                "type": "RFID",
                "uid": token_id,
                "valid": True,
                "whitelist": "NEVER",
                "last_updated": datetime.now(pytz.utc).strftime(
                    settings.OCPI_DATE_FORMAT
                ),
            },
        }
        return {"data": data}
    logger.error(
        "Missing authorization status or billed party "
        f"in OICP response from Hubject ({settings.HUBJECT_OPERATOR_ID}). Unable to invoice session.",
        extra={"response_data": oicp_response},
    )
    return None
