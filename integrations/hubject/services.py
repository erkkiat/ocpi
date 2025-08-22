import logging
from datetime import datetime
from urllib.error import HTTPError
from urllib.parse import urljoin

import pytz
import requests
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db.models import Prefetch
from pydantic_core import PydanticSerializationError, ValidationError
from requests import Response

from integrations.hubject.client import HubjectClient
from integrations.hubject.ocpi_to_oicp_converter import (
    convert_to_charging_notification_progress,
    convert_to_charging_notification_start,
    convert_to_charging_notification_end,
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
    Identification,
    UID,
    RFIDMifareFamilyIdentificationClass,
    ChargingNotificationType,
    ChargingNotificationBase,
    ERoamingPushEvseStatus,
    OperatorEvseStatus,
    EvseStatusRecordItem,
    EvseID,
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
from ocpiconnector.ocpi_identities import get_our_identity, get_our_credentialsrole
from ocpiconnector.party import Party
from util import with_trailing_slash
from typing import Any, TYPE_CHECKING
from ocpi22.tasks import send_hubject_request

if TYPE_CHECKING:
    from ocpi22.models.session import Session

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

        try:
            payload = ERoamingAuthorizeStart(
                operator_id=OperatorID(root=operator_id),
                identification=Identification(
                    RFIDMifareFamilyIdentification=RFIDMifareFamilyIdentificationClass(
                        UID=UID(root=token_id)
                    )
                ),
            )
            payload_dict = payload.model_dump(exclude_none=True, by_alias=True)
        except ValidationError:
            logger.exception()
            raise
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
            logger.info(
                f"Hubject authorize for token: {token_id} and operator id: {operator_id} responded: {response_json}"
            )
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
    def create_charging_notification_payload(
        cls, session, notification_type: ChargingNotificationType
    ) -> ChargingNotificationBase:
        match notification_type:
            case ChargingNotificationType.Start:
                payload = convert_to_charging_notification_start(session)
            case ChargingNotificationType.End:
                payload = convert_to_charging_notification_end(session)
            case ChargingNotificationType.Progress:
                payload = convert_to_charging_notification_progress(session)
            case _:
                raise ValueError(
                    f"Unsupported session notification type: {notification_type}"
                )
        return payload

    @classmethod
    def send_update(
        cls,
        session: "Session",
        notification_type: ChargingNotificationType,
    ) -> None:
        """
        Send an update to the OICP client based on the session and update type.
        """
        payload = cls.create_charging_notification_payload(session, notification_type)
        try:
            cls.post_charging_notification(payload)
            logger.info("Notification sent successfully")
        except requests.exceptions.HTTPError as e:
            logger.error(
                f"HTTP error: {e.response.status_code}",
                exc_info=True,
                extra={"hubject_response": e.response.text},
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error: {e}")
        except Exception as e:
            logger.exception(e)
        return

    @staticmethod
    def post_charging_notification(
        payload,
    ) -> Response:
        url = f"{settings.HUBJECT_URL}notificationmgmt/v11/charging-notifications"
        response = HubjectService.client.post(
            url, json=payload.model_dump(mode="json", by_alias=True)
        )
        response.raise_for_status()
        return response

    @classmethod
    def _get_evse_status_update_payload(
        cls, evse: Evse, operator_id: str, operator_name: str
    ) -> ERoamingPushEvseStatus:
        return ERoamingPushEvseStatus(
            action_type=ActionType.update,
            operator_evse_status=OperatorEvseStatus(
                operator_id=OperatorID(root=operator_id),
                operator_name=operator_name,
                evse_status_record=[
                    EvseStatusRecordItem(
                        evse_id=EvseID(root=evse.evse_id),
                        evse_status=cls.converter.convert_ocpi_evse_status(evse.status),
                    )
                ],
            ),
        )

    @classmethod
    def _get_evse_status_full_load_payload(
        cls, operator_id: str, our_credentials_role: CredentialsRole | None = None
    ) -> ERoamingPushEvseStatus | None:
        evse_record_items = []

        for e in (
            Evse.objects.values_list("evse_id", "status")
            .filter(location__ocpi_master=our_credentials_role)
            .iterator(chunk_size=100)
        ):
            evse_record_items.append(
                EvseStatusRecordItem(
                    evse_id=EvseID(root=e[0]),
                    evse_status=cls.converter.convert_ocpi_evse_status(e[1]),
                )
            )

        if not evse_record_items:
            logger.warning("No EVSE records found")
            return None

        return ERoamingPushEvseStatus(
            action_type=ActionType.fullLoad,
            operator_evse_status=OperatorEvseStatus(
                operator_id=OperatorID(root=operator_id),
                operator_name=our_credentials_role.business_details.name,
                evse_status_record=evse_record_items,
            ),
        )

    @classmethod
    def post_eroaming_push_evse_status(
        cls, evse: Evse, retries=3, full_load=False
    ) -> None:
        if not evse and not full_load:
            logger.warning("No EVSE provided for hubject status update")
            return
        ocpi_master = evse.location.ocpi_master
        operator_id = f"{ocpi_master.country_code}*{ocpi_master.party_id}"
        operator_name = ocpi_master.business_details.name

        try:
            if full_load:
                our_credentials_role = get_our_credentialsrole(OcpiRolesEnum.CPO.value)
                payload = cls._get_evse_status_full_load_payload(
                    operator_id, our_credentials_role
                )
            else:
                payload = cls._get_evse_status_update_payload(
                    evse, operator_id, operator_name
                )
        except (ValidationError, ValueError):
            logger.error(
                "Failed to create payload for EVSE status update", exc_info=True
            )
            return

        if not payload:
            logger.warning("No payload created for EVSE status update")
            return

        payload_json = payload.model_dump(mode="json", by_alias=True)

        url = (
            f"{settings.HUBJECT_URL}evsepush/v21/operators/{operator_id}/status-records"
        )

        send_hubject_request.delay(payload_json, url, "post")
