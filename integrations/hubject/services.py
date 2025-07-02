import logging
from datetime import datetime
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin

import pytz
import requests
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db.models import Prefetch
from pydantic_core import PydanticSerializationError
from requests import Response

from integrations.hubject.client import HubjectClient
from integrations.hubject.ocpi_to_oicp_converter import (
    convert_ocpi_session_to_oicp_charging_notification_progress,
    convert_ocpi_session_to_oicp_charging_notification_start,
    convert_ocpi_session_to_oicp_charging_notification_end,
)
from integrations.hubject.oicp_to_ocpi_converter import (
    map_oicp_authorization_response_to_ocpi_221,
)
from integrations.hubject.schemas import (
    ERoamingPushEvseData,
    ActionType,
    OperatorEvseData,
    PricingProductData,
    ERoamingPushPricingProductData,
    OperatorID,
    ERoamingAuthorizeStart,
    IdentificationClass,
    UID,
    RFIDMifareFamilyIdentificationClass,
    ChargingNotificationBase,
    ChargingNotificationType,
)
from integrations.solid_to_hubject_converter import SolidToHubjectConverter
from integrations.hubject.schemas import HubjectDefaultTariff
from ocpi22.choices import OcpiRolesEnum
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.location import Location, Connector, Evse
from ocpi22.models.tariff import SolidTariff
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.util import Ocpi
from ocpiconnector.exceptions import ConnectorTariffNotFoundError
from ocpiconnector.ocpi_identities import get_our_identity
from ocpiconnector.party import Party
from util import with_trailing_slash

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


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
                    if len(connector.get_tariffs()) == 0:
                        raise ConnectorTariffNotFoundError(
                            evse.evse_id,
                            connector.standard,
                            f"No Tariff found for Evse {evse.evse_id} and connector {connector.standard}",
                        )

        if len(evse_data_records) == 0:
            return None

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
            payload_json = payload.model_dump(mode="json")

            response = HubjectService.client.post(full_load_url, json=payload_json)
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "success": False,
                    "errorType": "HTTP Error",
                    "error": f"{response.status_code} : {response.text}",
                }
        except PydanticSerializationError as e:
            logger.exception("Pydantic validation failed")
            return {
                "success": False,
                "errorType": "Pydantic validation failed",
                "error": e.args[0],
            }
        except HTTPError as exc:
            logger.exception("HTTP error occurred")
            return {
                "success": False,
                "errorType": "HTTP request failed",
                "error": exc.args[0],
            }

    @staticmethod
    async def post_authorize_request(
        operator_id: str, token_id: str
    ) -> tuple[Any, dict | None, Any]:
        url = f"{with_trailing_slash(settings.HUBJECT_URL)}charging/v21/operators/{operator_id}/authorize/start"

        payload = ERoamingAuthorizeStart(
            OperatorID=OperatorID(root=operator_id),
            Identification=IdentificationClass(
                RFIDMifareFamilyIdentification=RFIDMifareFamilyIdentificationClass(
                    UID=UID(root=token_id)
                )
            ),
        )
        payload_dict = payload.model_dump(exclude_none=True)

        try:
            response = HubjectService.client.post(
                url, json=payload_dict, headers={"accept": "application/json"}
            )
        except requests.exceptions.RequestException:
            logger.exception("Requests exception during authorization with Hubject")
            return (
                404,
                {
                    "allowed": "NOT_ALLOWED",
                    "status_code": Ocpi.ServerError.GENERIC_SERVER_ERROR,
                    "status_message": "Request error occurred",
                    "timestamp": datetime.now(pytz.utc).strftime(
                        settings.OCPI_DATE_FORMAT
                    ),
                },
                CredentialsRole.objects.none(),
            )

        try:
            response_json = response.json()
            logging.info(response)
            status_code = response_json.get("StatusCode", {}).get("Code")

            ocpi_master = None
            if response.status_code == 200 and status_code == "000":
                ocpi_master = await sync_to_async(get_credentialsrole)(
                    credentials=None,
                    party=Party.from_str(response_json.get("ProviderID", "*")),
                    create=True,
                    role=OcpiRolesEnum.EMSP,
                )

            mapped_response = map_oicp_authorization_response_to_ocpi_221(
                response_json, token_id
            )
            return (
                response.status_code,
                mapped_response,
                ocpi_master,  # Todo: Rename ocpi_master, since it is used for OICP MSP identification also
            )
        except Exception:
            logger.exception("Exception during authorization with Hubject")
            return (
                404,
                {
                    "allowed": "NOT_ALLOWED",
                    "status_code": Ocpi.ServerError.GENERIC_SERVER_ERROR,
                    "status_message": "",
                    "timestamp": datetime.now(pytz.utc).strftime(
                        settings.OCPI_DATE_FORMAT
                    ),
                },
                CredentialsRole.objects.none(),
            )

    def get_default_tariffs(self):
        if not (
            settings.DEFAULT_OICP_PRICE
            and settings.DEFAULT_OICP_CURRENCY
            and settings.DEFAULT_OICP_PRICE_REFERENCE
        ):
            raise ValueError(
                "Please set DEFAULT_OICP_PRICE, DEFAULT_OICP_CURRENCY, and DEFAULT_OICP_REFERENCE in environment variables"
            )

        default_price = float(settings.DEFAULT_OICP_PRICE)
        default_currency = settings.DEFAULT_OICP_CURRENCY
        default_reference = settings.DEFAULT_OICP_PRICE_REFERENCE

        if default_price < 0:
            raise ValueError("DEFAULT_OICP_PRICE must be positive")

        solid_price_component = HubjectDefaultTariff.get_price_component(
            default_reference
        )
        return HubjectDefaultTariff(
            currency=default_currency,
            price_component=solid_price_component,
            price=default_price,
        )

    def get_all_pricing_products(self, party: Party) -> PricingProductData:
        solid_tariffs = SolidTariff.objects.filter(
            operator__country_code=party.country_code,
            operator__party_id=party.party_id,
        )

        if len(solid_tariffs) == 0:
            raise SolidTariff.DoesNotExist(f"No SolidTariffs found for {str(party)}")

        solid_default_tariff = self.get_default_tariffs()

        operator_name = solid_tariffs[0].operator.business_details.name
        return HubjectService.converter.convert_to_pricing_product_data(
            solid_tariffs,
            solid_default_tariff,
            get_our_identity(OcpiRolesEnum.CPO.value),
            operator_name,
        )

    def get_push_pricing_product_data_payload(
        self, pricing_product_data: PricingProductData, action_type: ActionType
    ) -> ERoamingPushPricingProductData:
        return ERoamingPushPricingProductData(
            ActionType=action_type,
            PricingProductData=pricing_product_data,
        )

    def post_pricing_products_full_load(
        self, operator_id: str, payload: ERoamingPushPricingProductData
    ) -> dict:
        full_load_url = urljoin(
            with_trailing_slash(settings.HUBJECT_URL),
            f"dynamicpricing/v10/operators/{operator_id}/pricing-products",
        )

        try:
            payload_json = payload.model_dump(mode="json")

            response = HubjectService.client.post(full_load_url, json=payload_json)
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "success": False,
                    "errorType": "HTTP Error",
                    "error": f"{response.status_code} : {response.text}",
                }
        except PydanticSerializationError as e:
            logger.exception("Pydantic validation failed")
            return {
                "success": False,
                "errorType": "Pydantic validation failed",
                "error": str(e),
            }

    @classmethod
    def send_update(
        cls, session, update_type: ChargingNotificationType
    ) -> Response | None:
        match update_type:
            case ChargingNotificationType.Start:
                return cls.post_hubject_charging_notification(
                    convert_ocpi_session_to_oicp_charging_notification_start(session)
                )
            case ChargingNotificationType.End:
                return cls.post_hubject_charging_notification(
                    convert_ocpi_session_to_oicp_charging_notification_end(session)
                )
            case ChargingNotificationType.Progress:
                return cls.post_hubject_charging_notification(
                    convert_ocpi_session_to_oicp_charging_notification_progress(session)
                )
        return None

    @staticmethod
    def post_hubject_charging_notification(
        payload: ChargingNotificationBase,
    ) -> Response | None:
        url = urljoin(
            with_trailing_slash(settings.HUBJECT_URL),
            "notificationmgmt/v11/charging-notifications",
        )
        try:
            response = HubjectService.client.post(
                url, json=payload.model_dump(mode="json")
            )
            if response.status_code != 200:
                logger.error(
                    f"Failed to send updates to Hubject: {response.status_code} - {response.text}"
                )
            return response
        except requests.exceptions.RequestException:
            logger.exception(
                "Request exception during sending ChargingNotification to Hubject"
            )
        return None
