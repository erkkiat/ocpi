import logging
import re
from datetime import datetime
from json import JSONDecodeError
from typing import Any
from collections import defaultdict
from urllib.error import HTTPError
from functools import lru_cache

import pytz
import requests
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db.models import Prefetch, QuerySet
from django.urls import reverse
from pydantic_core import PydanticSerializationError, ValidationError
from requests import Response

from integrations.hubject.exceptions import HubjectRemoteCommandError
from integrations.hubject.ocpi_to_oicp_converter import (
    convert_to_charging_notification_progress,
    convert_to_charging_notification_start,
    convert_to_charging_notification_end,
)
from integrations.hubject.oicp_to_ocpi_converter import (
    map_successful_oicp_authorization_response_to_ocpi_221,
)
from integrations.hubject.schemas import (
    ERoamingPushEvseData,
    ActionType,
    OperatorEvseData,
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
    ERoamingAcknowledgment,
    ERoamingAuthorizeRemoteStart,
    StatusCode,
    ERoamingAuthorizeRemoteStop,
    STATUS_CODE_TEXT,
    SessionID,
    PricingProductData,
    ERoamingPushPricingProductData,
    ERoamingPushEVSEPricing,
    ProviderIDAsterisk,
    EVSEPricingItem,
)
from integrations.solid_to_hubject_converter import SolidToHubjectConverter
from integrations.hubject.schemas import HubjectDefaultTariff
from ocpi22.choices import OcpiRolesEnum, TokenType
from ocpi22.cpo.repositories import CredentialsRepository, EvseRepository
from ocpi22.exceptions import EvseOccupiedError, EvseNotFoundError
from ocpi22.models.location import Location, Connector, Evse
from ocpi22.models.tariff import SolidTariff
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.util import Ocpi, OCPIResponse
from ocpi22.util import build_absolute_uri
from ocpiconnector.exceptions import ConnectorTariffNotFoundError
from ocpiconnector.ocpi_identities import (
    get_our_identity,
    get_our_party,
    get_our_credentialsrole,
)
from ocpiconnector.party import Party
from util import with_trailing_slash
from typing import TYPE_CHECKING, Optional
import aiohttp
import asyncio
import ssl
from aiohttp import ClientError
from ocpi22.tasks import send_hubject_request, get_certificate_loaded_request

if TYPE_CHECKING:
    from ocpi22.models.session import Session
    from ocpi22.models.cdr import Cdr


logger = logging.getLogger(__name__)


class HubjectService:
    REQUEST_TIMEOUT = 20
    CHARGING_NOTIFICATION_TIMEOUT = 40
    FULL_LOAD_TIMEOUT = 600

    converter = SolidToHubjectConverter()

    @staticmethod
    @lru_cache(maxsize=1)
    def _get_hubject_credentials_id() -> int | None:
        role = CredentialsRepository.find_hubject_credentials_role()
        if settings.ENABLE_HUBJECT:
            if not role or not role.credentials:
                raise ValueError("Hubject credentials not found.")
            return role.credentials.id
        return None

    # This init is used to fail fast execution if the credentials are not present
    def __init__(self):
        if settings.ENABLE_HUBJECT:
            HubjectService._get_hubject_credentials_id()

    @staticmethod
    def _get_request() -> requests.Session:
        cred_id = HubjectService._get_hubject_credentials_id()
        return get_certificate_loaded_request(cred_id)

    @staticmethod
    def get_operator_evse_data(party: Party) -> OperatorEvseData | None:
        hubject_credentials_role = CredentialsRepository.find_hubject_credentials_role()
        if not hubject_credentials_role:
            return None

        allowed_locations = hubject_credentials_role.credentials.allowed_locations

        location_filter = {
            "ocpi_master__party_id": party.party_id,
            "ocpi_master__country_code": party.country_code,
            "roaming_enabled": True,
        }

        if allowed_locations:
            location_filter["uid__in"] = allowed_locations

        locations = Location.objects.filter(**location_filter).prefetch_related(
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

        if not locations.exists():
            logger.warning(
                f"No locations found for operator {str(party)} to prepare EVSE data"
            )
            return None

        evse_data_records = []
        connectors_with_no_tariffs = []
        operator_name = None

        for location in locations.iterator(chunk_size=10):
            tmp_operator_evse_data = (
                HubjectService.converter.convert_to_operator_evse_data(location)
            )
            evse_data_records.extend(tmp_operator_evse_data.EvseDataRecord)
            operator_name = tmp_operator_evse_data.OperatorName

            for evse in location.evses_with_connectors:
                for connector in evse.connectors_with_tariffs:
                    if len(connector.get_tariffs()) == 0:
                        connectors_with_no_tariffs.append(
                            (location.uid, evse.uid, connector.uid)
                        )

        if connectors_with_no_tariffs:
            logger.error(
                "EVSE Full Load Failed: There are connectors with no tariffs",
                extra={"connectors_with_no_tariffs": connectors_with_no_tariffs},
                exc_info=True,
            )
            raise ConnectorTariffNotFoundError(
                "There are connectors with no tariffs",
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
            return None

        return ERoamingPushEvseData(
            ActionType=ActionType.fullLoad,
            OperatorEvseData=operator_evse_data,
        )

    @staticmethod
    def parse_hubject_validation_errors(
        response_json: dict,
        payload: ERoamingPushEvseData | ERoamingPushPricingProductData,
    ) -> dict:
        try:
            result = {
                "message": response_json.get("message", "Unknown error"),
                "errors": [],
                "error_count": 0,
                "field_summary": {},
                "status_code": 400,
            }

            validation_errors = response_json.get("validationErrors", [])
            result["error_count"] = len(validation_errors)

            for error in validation_errors:
                field_ref = error.get("fieldReference", "unknown")
                error_msg = error.get("errorMessage", "No error message")

                match = re.search(r"\[(\d+)\]", field_ref)
                if match:
                    index = int(match.group(1))
                else:
                    index = None
                    logger.warning(
                        f"Unexpected fieldReference format: '{field_ref}'. Could not determine the index."
                    )
                record_id = "Unknown"
                if isinstance(payload, ERoamingPushEvseData):
                    evse_record = (
                        payload.OperatorEvseData.EvseDataRecord[index]
                        if index is not None
                        and index < len(payload.OperatorEvseData.EvseDataRecord)
                        else None
                    )
                    record_id = evse_record.EvseID if evse_record else "Unknown"
                elif isinstance(payload, ERoamingPushPricingProductData):
                    price_record = (
                        payload.PricingProductData.PricingProductDataRecords[index]
                        if index is not None
                        and index
                        < len(payload.PricingProductData.PricingProductDataRecords)
                        else None
                    )
                    record_id = (
                        price_record.ProductID.root if price_record else "Unknown"
                    )

                formatted_error = (
                    f"Field: {field_ref} - UID: {record_id} - Error: {error_msg}"
                )

                result["errors"].append(formatted_error)

                if "." in field_ref:
                    field_pattern = (
                        field_ref.split("].")[-1]
                        if "]." in field_ref
                        else field_ref.split(".")[-1]
                    )
                    if field_pattern not in result["field_summary"]:
                        result["field_summary"][field_pattern] = 0
                    result["field_summary"][field_pattern] += 1

            return result
        except Exception:
            logger.exception("Error parsing Hubject validation errors")
            return {
                "message": "Failed to parse validation errors",
                "errors": response_json,
                "error_count": 1,
                "field_summary": {},
                "status_code": 500,
            }

    @staticmethod
    def post_evse_full_load(operator_id: str, payload: ERoamingPushEvseData) -> dict:
        full_load_url = (
            f"{settings.HUBJECT_URL}evsepush/v23/operators/{operator_id}/data-records"
        )

        try:
            payload_json = payload.model_dump(mode="json")

            response = HubjectService._get_request().post(
                full_load_url,
                json=payload_json,
                timeout=HubjectService.FULL_LOAD_TIMEOUT,
            )
            if response.status_code == 200:
                return response.json()
            else:
                try:
                    response_json = response.json()
                    formatted_errors = HubjectService.parse_hubject_validation_errors(
                        response_json, payload
                    )
                except JSONDecodeError:
                    formatted_errors = f"{response.status_code} : {response.text}"

                logger.error(
                    f"Hubject EVSE full load failed with status code {response.status_code}",
                    extra={"response_text": formatted_errors},
                )
                return {
                    "success": False,
                    "errorType": "HTTP Error",
                    "error": formatted_errors,
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
        operator_id: str,
        token_id: str,
        session: aiohttp.ClientSession,
        ssl_context: ssl.SSLContext | None,
    ) -> tuple[Any, dict | None, Any]:
        url = f"{with_trailing_slash(settings.HUBJECT_URL)}charging/v21/operators/{operator_id}/authorize/start"

        try:
            payload = ERoamingAuthorizeStart(
                operator_id=OperatorID(root=operator_id),
                identification=Identification(
                    RFIDMifareFamilyIdentification=RFIDMifareFamilyIdentificationClass(
                        UID=UID(root=token_id)
                    ),
                    RemoteIdentification=None,
                    QRCodeIdentification=None,
                    RFIDIdentification=None,
                    PlugAndChargeIdentification=None,
                ),
            )
            payload_dict = payload.model_dump(exclude_none=True, by_alias=True)
        except ValidationError:
            logger.exception("Validation failed for Hubject authorization")
            return (
                400,
                {
                    "allowed": "NOT_ALLOWED",
                    "status_code": Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                    "status_message": "Validation failed for Hubject authorization",
                    "timestamp": datetime.now(pytz.utc).strftime(
                        settings.OCPI_DATE_FORMAT
                    ),
                },
                None,
            )

        response_json, response_status = None, None
        
        try:
             response = await session.post(
                url,
                json=payload_dict,
                headers={"accept": "application/json", "Content-Type": "application/json"},
                timeout=HubjectService.REQUEST_TIMEOUT,
                ssl=ssl_context
            )
             response_status = response.status
             response_json = await response.json()
             
        except (aiohttp.ContentTypeError, JSONDecodeError):
            logger.exception(
                f"Cannot decode JSON response from url {url}",
                extra={"status_code": response_status},
            )
            response_json = None
        except ClientError:
             logger.error(
                f"Cannot connect to {url} for token authorization", exc_info=True
            )
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
                None,
            )
        except (TimeoutError, asyncio.TimeoutError):
             logger.error(
                f"Timeout connecting to {url}", exc_info=True
            )
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
                None
             )
        except Exception:
             logger.error(
                f"Generic error connecting to {url}", exc_info=True
            )
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
                None
             )


        try:
            logger.info(
                f"Hubject authorize for token: {token_id} and operator id: {operator_id} responded: {response_json}"
            )

            oicp_status_code = response_json.get("StatusCode", {}).get("Code") if response_json else None
            
            mapped_response = None
            ocpi_master = None
            
            if response_status == 200 and oicp_status_code == "000":
                 ocpi_master = await sync_to_async(get_credentialsrole)(
                    credentials=None,
                    party=Party.from_str(response_json.get("ProviderID", "*")),
                    create=True,
                    role=OcpiRolesEnum.EMSP,
                )
                 mapped_response = (
                    map_successful_oicp_authorization_response_to_ocpi_221(
                        response_json, token_id
                    )
                )
            else:
                 logger.warning(
                    f"Authorization failed with status code {response_status or 'Unknown'} "
                    f"and Hubject error code {oicp_status_code or 'Unknown'} ({STATUS_CODE_TEXT.get(oicp_status_code, 'Unknown')})"
                )

            return (
                response_status,
                mapped_response,
                ocpi_master,
            )
        except Exception:
             logger.error("Error processing Hubject response" , exc_info=True)
             return (
                500,
                {
                    "allowed": "NOT_ALLOWED",
                    "status_code": Ocpi.ServerError.GENERIC_SERVER_ERROR,
                    "status_message": "",
                     "timestamp": datetime.now(pytz.utc).strftime(
                        settings.OCPI_DATE_FORMAT
                     ),
                },
                None
             )
        except Exception:
             logger.error("Error processing Hubject response", exc_info=True)
             return (
                500,
                {
                    "allowed": "NOT_ALLOWED",
                    "status_code": Ocpi.ServerError.GENERIC_SERVER_ERROR,
                    "status_message": "Error processing Hubject response",
                     "timestamp": datetime.now(pytz.utc).strftime(
                        settings.OCPI_DATE_FORMAT
                     ),
                },
                None
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
        full_load_url = f"{settings.HUBJECT_URL}dynamicpricing/v10/operators/{operator_id}/pricing-products"

        try:
            payload_json = payload.model_dump(mode="json")

            response = HubjectService._get_request().post(
                full_load_url,
                json=payload_json,
                timeout=HubjectService.FULL_LOAD_TIMEOUT,
            )
            if response.status_code == 200:
                return response.json()
            else:
                try:
                    response_json = response.json()
                    formatted_errors = HubjectService.parse_hubject_validation_errors(
                        response_json, payload
                    )
                except JSONDecodeError:
                    formatted_errors = f"{response.status_code} : {response.text}"

                logger.error(
                    f"Hubject Pricing Product full load failed with status code {response.status_code}",
                    extra={"response_text": formatted_errors},
                )
                return {
                    "success": False,
                    "errorType": "HTTP Error",
                    "error": formatted_errors,
                }
        except PydanticSerializationError as e:
            logger.exception("Pydantic validation failed")
            return {
                "success": False,
                "errorType": "Pydantic validation failed",
                "error": str(e),
            }

    def evse_product_id_map_generator(self, evses: QuerySet) -> defaultdict:
        evse_pricing_product_id_map = defaultdict(list)

        for evse in evses:
            connector = (
                evse.connectors_with_tariffs[0]
                if evse.connectors_with_tariffs
                else None
            )  # One evse has one connector
            if not connector:
                logger.info(f"Evse {evse.uid} has no connectors")
                continue
            pricing_product_ids = []

            for tariff in connector.tariff_ids.all():
                solid_tariff = tariff.solid_tariff.first()
                external_id = solid_tariff.external_id if solid_tariff else None
                pricing_product_id = self.converter.get_pricing_product_id(
                    external_id,
                    tariff.uid,
                )
                pricing_product_ids.append(pricing_product_id)

            evse_pricing_product_id_map[evse.evse_id] = pricing_product_ids
        return evse_pricing_product_id_map

    def get_evse_product_maps(self) -> defaultdict | None:
        hubject_credentials_role = CredentialsRepository.find_hubject_credentials_role()
        if not hubject_credentials_role or not hubject_credentials_role.credentials:
            return None

        party = get_our_party(OcpiRolesEnum.CPO)
        evses = CredentialsRepository.get_evses_by_party(
            hubject_credentials_role.credentials, party
        )

        evse_pricing_product_id_map = self.evse_product_id_map_generator(evses)

        return evse_pricing_product_id_map

    def get_evse_pricing_product_data_full_load_payload(
        self, evse_product_id_map: dict
    ) -> ERoamingPushEVSEPricing:
        evse_pricing_items = []
        for evse_id, product_ids in evse_product_id_map.items():
            evse_pricing_items.append(
                EVSEPricingItem(
                    EvseID=evse_id,
                    # todo: According to Mike we should have a list here. But as of now a list is not accepted by hubject
                    ProviderID=ProviderIDAsterisk("*"),
                    EvseIDProductList=product_ids,
                )
            )

        return ERoamingPushEVSEPricing(
            ActionType=ActionType.fullLoad, EVSEPricing=evse_pricing_items
        )

    def post_evse_pricing_item_full_load(self, payload: ERoamingPushEVSEPricing):
        operator_id = get_our_identity(OcpiRolesEnum.CPO.value)
        full_load_url = f"{settings.HUBJECT_URL}dynamicpricing/v10/operators/{operator_id}/evse-pricing"

        try:
            payload_json = payload.model_dump(mode="json")
        except PydanticSerializationError as e:
            logging.exception(e)
            return {
                "success": False,
                "errorType": "Pydantic validation failed",
                "error": str(e),
            }

        try:
            response = HubjectService._get_request().post(
                full_load_url,
                json=payload_json,
                timeout=HubjectService.FULL_LOAD_TIMEOUT,
            )
            return response.json()
        except HTTPError as exc:
            logging.error(exc)
            return {
                "success": False,
                "errorType": "HTTP request failed",
                "error": str(exc),
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
        if notification_type == ChargingNotificationType.Progress:
            kwh = session.kwh
            if kwh == 0:
                logger.info(
                    f"Ignored progress notification for session {session.uid} with kWh {kwh}"
                )
                return
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
            logger.error(f"Network error: {e.args[0]}", exc_info=True)
        except Exception as e:
            logger.exception(e)
        return

    @staticmethod
    def post_charging_notification(
        payload,
    ) -> Response:
        url = f"{settings.HUBJECT_URL}notificationmgmt/v11/charging-notifications"
        response = HubjectService._get_request().post(
            url,
            json=payload.model_dump(mode="json", by_alias=True),
            timeout=HubjectService.CHARGING_NOTIFICATION_TIMEOUT,
        )
        response.raise_for_status()
        return response

    @classmethod
    def _get_evse_status_update_payload(
        cls, evse: Evse
    ) -> ERoamingPushEvseStatus | None:
        if not evse:
            return None
        ocpi_master = evse.location.ocpi_master
        operator_id = f"{ocpi_master.country_code}*{ocpi_master.party_id}"
        operator_name = ocpi_master.business_details.name

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
    def _get_evse_status_full_load_payload(cls) -> ERoamingPushEvseStatus | None:
        our_credentials_role = get_our_credentialsrole(OcpiRolesEnum.CPO)
        if not our_credentials_role:
            logger.error("Cannot determine our credentials role for CPO")
            return None
        evse_record_items = []

        for evse_id, status in EvseRepository.iterate_status_by_credentials(
            our_credentials_role
        ):
            evse_record_items.append(
                EvseStatusRecordItem(
                    evse_id=EvseID(root=evse_id),
                    evse_status=cls.converter.convert_ocpi_evse_status(status),
                )
            )

        if not evse_record_items:
            logger.warning("No EVSE records found")
            return None

        return ERoamingPushEvseStatus(
            action_type=ActionType.fullLoad,
            operator_evse_status=OperatorEvseStatus(
                operator_id=OperatorID(root=our_credentials_role.party_str()),
                operator_name=our_credentials_role.business_details.name,
                evse_status_record=evse_record_items,
            ),
        )

    @classmethod
    def post_eroaming_push_evse_status(cls, evse: Evse, full_load=False) -> None:
        if not evse and not full_load:
            logger.warning("No EVSE provided for hubject status update")
            return
        try:
            if full_load:
                payload = cls._get_evse_status_full_load_payload()
                timeout = cls.FULL_LOAD_TIMEOUT
            else:
                payload = cls._get_evse_status_update_payload(evse)
                timeout = cls.REQUEST_TIMEOUT
        except (ValidationError, ValueError):
            logger.error(
                "Failed to create payload for EVSE status update", exc_info=True
            )
            return

        if not payload:
            logger.warning("No payload created for EVSE status update")
            return

        operator_id = payload.operator_evse_status.operator_id.root

        payload_json = payload.model_dump(mode="json", by_alias=True)

        url = (
            f"{settings.HUBJECT_URL}evsepush/v21/operators/{operator_id}/status-records"
        )

        cred_id = HubjectService._get_hubject_credentials_id()
        send_hubject_request.delay(payload_json, url, timeout, cred_id, method="post")

    @staticmethod
    def post_eroaming_charge_detail_record(
        operator_id: str, cdr: Optional["Cdr"], session_id=None, retries=3
    ) -> dict:
        from ocpi22.models.cdr import Cdr

        if cdr is None:
            if session_id is None:
                logger.warning(
                    "Neither CDR nor session_id provided for CDR post for Hubject"
                )
                return {
                    "success": False,
                    "errorType": "Invalid Input",
                    "error": "Either CDR or session_id must be provided.",
                }

            cdr = Cdr.objects.filter(session_id=session_id).first()
            if not cdr:
                logger.warning(f"No CDR found for session_id {session_id}")
                return {
                    "success": False,
                    "errorType": "Invalid Input",
                    "error": f"No CDR found for session_id {session_id}.",
                }
            if not cdr.route_through_oicp:
                logger.warning(
                    f"CDR for session_id {session_id} has not routed through OICP"
                )
                return {
                    "success": False,
                    "errorType": "Incompatible CDR",
                    "error": f"CDR with session id {session_id} has not routed through OICP",
                }

        url = f"{settings.HUBJECT_URL}cdrmgmt/v22/operators/{operator_id}/charge-detail-record"

        try:
            payload = (
                HubjectService.converter.convert_cdr_to_eroaming_charging_detail_record(
                    cdr
                )
            )
            payload_json = payload.model_dump(
                mode="json", exclude_none=True, by_alias=True
            )
        except ValidationError as ve:
            logger.error("Failed to create payload for Hubject CDR", exc_info=True)
            return {
                "success": False,
                "errorType": "Validation Error",
                "error": str(ve),
            }

        retry_policy = dict(max_retries=retries, interval_start=5)
        cred_id = HubjectService._get_hubject_credentials_id()
        send_hubject_request.apply_async(
            args=(payload_json, url, HubjectService.REQUEST_TIMEOUT, cred_id, "post"),
            retry=True,
            retry_policy=retry_policy,
        )
        logger.info("Hubject CDR post task queued")
        return {
            "success": True,
            "message": "Sent CDR to hubject",
        }

    @staticmethod
    def decode_country_code_and_party_id(
        provider_id: str | None,
    ) -> tuple[str | None, str | None]:
        if provider_id is None:
            return None, None

        asterisk_count = provider_id.count("*")
        dash_count = provider_id.count("-")

        if (
            asterisk_count > 1
            or dash_count > 1
            or (asterisk_count > 0 and dash_count > 0)
        ):
            raise ValueError(f"Invalid ProviderID format: {provider_id}")

        if "*" in provider_id:
            return tuple(provider_id.split("*", 1))
        elif "-" in provider_id:
            return tuple(provider_id.split("-", 1))
        elif len(provider_id) == 5 and provider_id.isalnum():
            # Assuming the format is 'CCPPP' where CC is country code and PPP is party ID
            return provider_id[:2], provider_id[2:]
        else:
            raise ValueError(f"Invalid ProviderID format: {provider_id}")

    def _prepare_start_session_data(
        self,
        remote_start_command: ERoamingAuthorizeRemoteStart,
        location_id: str,
        sender_party: Party,
    ) -> dict:
        authorization_reference = remote_start_command.session_id.root
        contract_id = (
            remote_start_command.identification.RemoteIdentification.EvcoID.root
        )
        if not contract_id:
            raise HubjectRemoteCommandError(
                "022", "EvcoID is required for remote start command"
            )
        return {
            "response_url": build_absolute_uri(
                reverse(
                    "chargepoint-remote-command-result", args=(authorization_reference,)
                )
            ),
            "token": {
                "uid": contract_id,  # Hubject does not send a token UID for remote start
                "country_code": sender_party.country_code,
                "party_id": sender_party.party_id,
                "type": TokenType.APP_USER.value,
                "contract_id": contract_id,
            },
            "location_id": location_id,
            "evse_uid": self._get_evse_uid(remote_start_command.evse_id.root),
            "connector_id": "",
            "authorization_reference": authorization_reference,
        }

    def _get_evse_uid(self, evse_id: str) -> str:
        if "*" in evse_id:
            return evse_id.split("*", 2)[-1][1:]
        if "-" in evse_id:
            return evse_id.split("-", 2)[-1][1:]
        return evse_id[6:]

    def _get_hubject_error_code(self, evse: Evse) -> str:
        if not evse:
            return "603"

        match evse.status:
            case Evse.AVAILABLE:
                return "000"  # Success
            case Evse.BLOCKED:
                return "501"
            case Evse.CHARGING:
                return "602"
            case Evse.INOPERATIVE:
                return "700"
            case Evse.OUTOFORDER:
                return "700"
            case Evse.PLANNED:
                return "501"
            case Evse.REMOVED:
                return "700"
            case Evse.RESERVED:
                return "601"
            case Evse.UNKNOWN:
                return "501"
            case _:
                return "000"

    def _create_error_acknowledgment(
        self, command: dict, error_code: str, error_message: str = None
    ) -> ERoamingAcknowledgment:
        return ERoamingAcknowledgment(
            result=False,
            status_code=StatusCode(Code=error_code, Description=error_message),
            session_id=SessionID(root=command.get("session_id", "")),
            cpo_partner_session_id="",
            emp_partner_session_id=command.get("emp_partner_session_id", ""),
        )

    def _get_sender_party(
        self, remote_start_command: ERoamingAuthorizeRemoteStart
    ) -> Party:
        try:
            sender_country_code, sender_party_id = (
                self.decode_country_code_and_party_id(
                    remote_start_command.provider_id.root
                )
            )
        except ValueError as ve:
            logger.error(f"Failed to decode ProviderID: {ve}")
            raise HubjectRemoteCommandError("300", "Invalid ProviderID format")

        return Party.from_str(f"{sender_country_code}*{sender_party_id}")

    def process_remote_start_command(
        self, remote_start_command: ERoamingAuthorizeRemoteStart
    ):
        from ocpi22.commands.serializers import StartSessionSerializer

        logger.info(
            "Remote start command received from Hubject",
            extra={"command": remote_start_command},
        )
        try:
            from ocpi22.commands.repository import LocationRepository

            location_id = LocationRepository.find_location_uid_by_evse_id(
                remote_start_command.evse_id.root
            )
            if not location_id:
                logger.error(
                    f"EVSE {remote_start_command.evse_id.root} not found for Hubject remote start"
                )
                raise EvseNotFoundError("Location and EVSE not found")
            sender_party = self._get_sender_party(remote_start_command)
            data = self._prepare_start_session_data(
                remote_start_command, location_id, sender_party
            )

            serializer = StartSessionSerializer(data=data)
            if serializer.is_valid():
                validated_data = serializer.validated_data
                return self._start_session(
                    sender_party, remote_start_command, validated_data
                )
            else:
                logger.error(
                    "Invalid data for starting remote session for Hubject",
                    extra={"errors": serializer.errors, "data": data},
                )
                return self._create_error_acknowledgment(
                    remote_start_command.model_dump(),
                    "022",
                    "Invalid data for starting session",
                )
        except HubjectRemoteCommandError as hubject_error:
            return self._create_error_acknowledgment(
                remote_start_command.model_dump(),
                hubject_error.error_code,
                hubject_error.args[0],
            )
        except EvseNotFoundError:
            return self._create_error_acknowledgment(
                remote_start_command.model_dump(), "603", "EVSE not found"
            )
        except EvseOccupiedError:
            return self._create_error_acknowledgment(
                remote_start_command.model_dump(),
                "602",
                "EVSE is currently occupied",
            )

    def _start_session(
        self,
        sender_party,
        remote_start_command: ERoamingAuthorizeRemoteStart,
        validated_data: dict,
    ) -> ERoamingAcknowledgment:
        from ocpi22.commands.services import StartCommandService
        from ocpi22.commands.repository import SessionRepository

        hubject_party = Party.from_str(settings.HUBJECT_OPERATOR_ID)
        # There is no hub authentication in OCPI 2.x
        credentials_role = get_credentialsrole(credentials=None, party=hubject_party)
        if not credentials_role:
            # This should be created as the part of the setup manually.
            logger.error("Hubject Remote Start failed: No hubject credentials found")
            raise HubjectRemoteCommandError("021", "Credentials not found for Hubject")

        service = StartCommandService()
        response = service.start_session(
            sender_party=sender_party,
            credentials=credentials_role.credentials,
            validated_data=validated_data,
            hub_session_id=remote_start_command.session_id.root,
        )
        self._validate_command_response(response, validated_data.get("evse_uid", None))

        session = SessionRepository.find_session_by_auth_ref_and_token_uid(
            validated_data.get("authorization_reference"),
            validated_data["token"]["uid"],
        )
        session_uid = session.uid if session else ""
        logger.info(
            f"Hubject remote start command processed successfully, session : {session_uid}"
        )
        return ERoamingAcknowledgment(
            result=True,
            status_code=StatusCode(Code="000"),
            session_id=remote_start_command.session_id,
            cpo_partner_session_id=session_uid,
            emp_partner_session_id=remote_start_command.emp_partner_session_id,
        )

    def _get_remote_stop_command_data(
        self, remote_stop_command: ERoamingAuthorizeRemoteStop
    ) -> dict:
        from ocpi22.commands.repository import SessionRepository

        command_id = remote_stop_command.emp_partner_session_id or None
        session = SessionRepository.find_session_by_hub_session_id(
            remote_stop_command.session_id.root
        )
        if not session:
            logger.error(
                f"No session found to stop with hub session id {remote_stop_command.session_id.root}, hubject remote stop failed"
            )
            raise HubjectRemoteCommandError("400", "Session not found")

        data = {
            "response_url": build_absolute_uri(
                reverse("chargepoint-remote-command-result", args=(command_id,))
            ),
            "session_id": session.uid,
        }
        return data

    def _validate_command_response(
        self, response: OCPIResponse, evse_uid: str | None
    ) -> None:
        from ocpi22.commands.serializers import CommandResponseType

        response_data = response.data

        data = response_data["data"]
        if not data:
            raise HubjectRemoteCommandError(
                "021", "Remote command failed", data={"accepted_status": False}
            )

        if response.status_code == 400:
            logger.warning(
                "Hubject remote command failed: HTTP error 400",
                extra={"response": response.data},
            )
            if data.get("evse_status") == "Occupied":
                raise HubjectRemoteCommandError(
                    "602",
                    "EVSE is occupied",
                    data={"accepted_status": False},
                )
            raise HubjectRemoteCommandError(
                "021",
                "Remote command failed due to HTTP error",
                data={"accepted_status": False},
            )

        result = data["result"]
        if result == CommandResponseType.UNKNOWN_SESSION:
            logger.error(
                "Hubject remote command failed: Session not found",
                extra={"response": response_data},
            )
            raise HubjectRemoteCommandError("400", "Session not found")
        if result != CommandResponseType.ACCEPTED:
            logger.error(
                "Hubject remote command was rejected", extra={"response": response_data}
            )
            raise HubjectRemoteCommandError(
                "021",
                "Remote command was rejected",
                data={"accepted_status": False},
            )
        logger.info(f"Hubject remote command was accepted. {data}")
        return

    def process_remote_stop_command(
        self, remote_stop_command: ERoamingAuthorizeRemoteStop
    ):
        from ocpi22.commands.serializers import StopSessionSerializer
        from ocpi22.commands.services import StopCommandServices

        try:
            logger.info(
                "Remote stop command received from Hubject",
                extra={
                    "command": remote_stop_command,
                    "evse": remote_stop_command.evse_id.root,
                },
            )

            data = self._get_remote_stop_command_data(remote_stop_command)

            serializer = StopSessionSerializer(data=data)
            if serializer.is_valid():
                validated_data = serializer.validated_data
            else:
                logger.error(
                    "Invalid data for stopping remote session for Hubject",
                    extra={"errors": serializer.errors, "data": data},
                )
                return self._create_error_acknowledgment(
                    remote_stop_command.model_dump(),
                    "022",
                    "Invalid data for stopping session",
                )

            service = StopCommandServices()
            response = service.stop_session(
                validated_data=validated_data,
            )

            self._validate_command_response(response, None)

            return ERoamingAcknowledgment(
                result=True,
                status_code=StatusCode(Code="000"),
                session_id=remote_stop_command.session_id,
                cpo_partner_session_id=data.get("session_id", None),
                emp_partner_session_id=remote_stop_command.emp_partner_session_id,
            )

        except HubjectRemoteCommandError as hubject_error:
            return self._create_error_acknowledgment(
                remote_stop_command.model_dump(),
                hubject_error.error_code,
                hubject_error.args[0],
            )
        except EvseNotFoundError:
            return self._create_error_acknowledgment(
                remote_stop_command.model_dump(), "603", "EVSE not found"
            )
