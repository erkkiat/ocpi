import logging
from datetime import datetime
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin

import pytz
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db.models import Prefetch
from pydantic_core import PydanticSerializationError

from integrations.hubject.client import HubjectClient
from integrations.hubject.schemas import (
    ERoamingPushEvseData,
    ActionType,
    OperatorEvseData,
    ERoamingAuthorizeStart,
    OperatorID,
    Identification,
    UID,
    RFIDMifareFamilyIdentification,
)
from integrations.solid_to_hubject_converter import SolidToHubjectConverter
from ocpi22.choices import OcpiRolesEnum
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.location import Location, Connector, Evse
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.util import Ocpi
from ocpiconnector.exceptions import ConnectorTariffNotFoundError
from ocpiconnector.party import Party
from util import with_trailing_slash

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def map_oicp_authorization_response_to_ocpi_221(
    oicp_response: dict, token_id: str
) -> dict | None:
    authorization_status = oicp_response.get("AuthorizationStatus")
    status_ok = oicp_response.get("StatusCode", {}).get("Code") == "000"
    country_code, party_id = oicp_response.get("ProviderID", "").split("*")

    if authorization_status and status_ok:
        data = {
            "allowed": {"Authorized": "ALLOWED"}.get(
                authorization_status, "NOT_ALLOWED"
            ),
            "authorization_reference": "HUBJECT",
            "hubject_session_id": oicp_response.get("SessionID"),
            "token": {
                "contract_id": "N/A",
                "country_code": country_code,
                "party_id": party_id,
                "default_profile_type": "REGULAR",
                "issuer": f"{country_code}*{party_id}",
                "language": settings.LANGUAGE_CODE.upper(),
                "last_updated": None,
                "type": "RFID",
                "uid": token_id,
                "valid": True,
                "whitelist": "NEVER",
            },
        }
        return {"data": data}
    return None


class HubjectService:
    client = HubjectClient()
    converter = SolidToHubjectConverter()

    @staticmethod
    def get_operator_evse_data(party: Party) -> OperatorEvseData | None:
        locations = Location.objects.filter(
            ocpi_master__party_id=party.party_id,
            ocpi_master__country_code=party.country_code,
        )
        evse_data_records = []
        operator_name = None

        if len(locations) == 0:
            return

        locations = Location.objects.prefetch_related(
            Prefetch(
                "evses",
                queryset=Evse.objects.prefetch_related(
                    Prefetch(
                        "connectors",
                        queryset=Connector.objects.prefetch_related("tariff_ids"),
                        to_attr="connectors_with_tariffs",
                    )
                ),
                to_attr="evses_with_connectors",
            )
        )

        for location in locations:
            tmp_operator_evse_data = (
                HubjectService.converter.convert_to_operator_evse_data(location)
            )
            evse_data_records.extend(tmp_operator_evse_data.EvseDataRecord)
            operator_name = tmp_operator_evse_data.OperatorName

            for evse in location.evses_with_connectors:
                for connector in evse.connectors_with_tariffs:
                    if not connector.get_tariffs():
                        raise ConnectorTariffNotFoundError(
                            evse.evse_id,
                            connector.standard,
                            f"No Tariff found for Evse {evse.evse_id} and connector {connector.standard}",
                        )

        if len(evse_data_records) == 0:
            return

        return OperatorEvseData(
            OperatorID=OperatorID(root=str(party)),
            OperatorName=operator_name,
            EvseDataRecord=evse_data_records,
        )

    def get_evse_full_load_payload(
        self, operator_id: Party
    ) -> ERoamingPushEvseData | None:
        operator_evse_data: OperatorEvseData = self.get_operator_evse_data(operator_id)

        if operator_evse_data is None:
            return

        return ERoamingPushEvseData(
            ActionType=ActionType.fullLoad,
            OperatorEvseData=operator_evse_data,
        )

    @staticmethod
    def post_evse_full_load(operator_id: str, payload: ERoamingPushEvseData) -> dict:
        full_load_url = urljoin(
            with_trailing_slash(settings.HUBJECT_URL),
            f"evsepush/v23/operators/{operator_id}/data-records",
        )

        try:
            payload_json = payload.model_dump_json()

            response = HubjectService.client.post(full_load_url, data=payload_json)
            return response.json()
        except PydanticSerializationError as e:
            logging.error(e)
            return {
                "success": False,
                "errorType": "Pydantic validation failed",
                "error": e.args[0],
            }
        except HTTPError as exc:
            logging.error(exc)
            return {
                "success": False,
                "errorType": "HTTP request failed",
                "error": exc.args[0],
            }

    @staticmethod
    async def post_authorize_request(
        operator_id: str, token_id: str
    ) -> tuple[Any, dict | None, Any]:
        url = urljoin(
            with_trailing_slash(settings.HUBJECT_URL),
            f"charging/v21/operators/{operator_id}/authorize/start",
        )

        try:
            payload = ERoamingAuthorizeStart(
                OperatorID=OperatorID(root=operator_id),
                Identification=Identification(
                    RFIDMifareFamilyIdentification=RFIDMifareFamilyIdentification(
                        UID=UID(root=token_id)
                    )
                ),
            )
            payload_json = payload.model_dump_json()

            response = HubjectService.client.post(url, data=payload_json)

            ocpi_master = await sync_to_async(get_credentialsrole)(
                credentials=None,
                party=Party.from_str(response.json().get("ProviderID")),
                create=True,
                role=OcpiRolesEnum.EMSP,
            )

            return (
                response.status_code,
                map_oicp_authorization_response_to_ocpi_221(response.json(), token_id),
                ocpi_master,
            )

        except (ValueError, OSError, RuntimeError):
            logger.exception("Authorization error with Hubject")
            return (
                404,
                {
                    "allowed": "NOT_ALLOWED",
                    "status_code": Ocpi.ServerError.GENERIC_SERVER_ERROR,
                    "status_message": "Error",
                    "timestamp": datetime.now(pytz.utc).strftime(
                        settings.OCPI_DATE_FORMAT
                    ),
                },
                CredentialsRole.objects.none(),
            )
