import logging
from datetime import datetime
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin

import pytz
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from pydantic_core import PydanticSerializationError
from rest_framework import status

from integrations.hubject.client import HubjectClient
from integrations.hubject.oicp_to_ocpi_converter import (
    map_oicp_authorization_response_to_ocpi_221,
)
from integrations.hubject.schemas import (
    ERoamingPushEvseData,
    ActionType,
    OperatorEvseData,
    ERoamingAuthorizeStart,
    OperatorID,
    Identification,
    UID,
    RFIDMifareFamilyIdentification,
    PricingProductData,
    ERoamingPushPricingProductData,
)
from integrations.solid_to_hubject_converter import SolidToHubjectConverter
from integrations.hubject.schemas import HubjectDefaultTariff
from ocpi22.choices import OcpiRolesEnum
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.cdr import Cdr
from ocpi22.models.location import Location, Connector, Evse
from ocpi22.models.tariff import SolidTariff
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.util import Ocpi
from ocpiconnector.exceptions import ConnectorTariffNotFoundError
from ocpiconnector.ocpi_identities import get_our_identity
from ocpiconnector.party import Party
from util import with_trailing_slash
from ocpi22.tasks import send_hubject_request

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
                OperatorID=OperatorID(root=operator_id),
                Identification=Identification(
                    RFIDMifareFamilyIdentification=RFIDMifareFamilyIdentification(
                        UID=UID(root=token_id)
                    )
                ),
            )
            payload_dict = payload.model_dump(exclude_none=True)

            response = HubjectService.client.post(url, json=payload_dict)

            logging.info(response)
            status_code = response.get("StatusCode", {}).get("Code")

            ocpi_master = None
            if response.status_code == status.HTTP_200_OK and status_code == "000":
                ocpi_master = await sync_to_async(get_credentialsrole)(
                    credentials=None,
                    party=Party.from_str(response.json().get("ProviderID", "*")),
                    create=True,
                    role=OcpiRolesEnum.EMSP,
                )

            return (
                response.status_code,
                map_oicp_authorization_response_to_ocpi_221(response.json(), token_id),
                ocpi_master,  # Todo: Rename ocpi_master, since it is used for OICP MSP identification also
            )

        except ValueError as ve:
            logger.exception("ValueError during authorization with Hubject: %s", ve)
            return (
                404,
                {
                    "allowed": "NOT_ALLOWED",
                    "status_code": Ocpi.ServerError.GENERIC_SERVER_ERROR,
                    "status_message": "Invalid data provided",
                    "timestamp": datetime.now(pytz.utc).strftime(
                        settings.OCPI_DATE_FORMAT
                    ),
                },
                CredentialsRole.objects.none(),
            )
        except OSError as oe:
            logger.exception("OSError during authorization with Hubject: %s", oe)
            return (
                404,
                {
                    "allowed": "NOT_ALLOWED",
                    "status_code": Ocpi.ServerError.GENERIC_SERVER_ERROR,
                    "status_message": "Network error occurred",
                    "timestamp": datetime.now(pytz.utc).strftime(
                        settings.OCPI_DATE_FORMAT
                    ),
                },
                CredentialsRole.objects.none(),
            )
        except RuntimeError as re:
            logger.exception("RuntimeError during authorization with Hubject: %s", re)
            return (
                404,
                {
                    "allowed": "NOT_ALLOWED",
                    "status_code": Ocpi.ServerError.GENERIC_SERVER_ERROR,
                    "status_message": "Unexpected runtime error",
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

    @staticmethod
    def post_eroaming_charge_detail_record(
        operator_id: str, cdr: Cdr | None, session_id=None, retries=3
    ) -> dict:
        if cdr is None:
            if session_id is None:
                return {
                    "success": False,
                    "errorType": "Invalid Input",
                    "error": "Either CDR or session_id must be provided.",
                }

            cdr = Cdr.objects.filter(session_id=session_id).first()
            if cdr is None:
                return {
                    "success": False,
                    "errorType": "Invalid Input",
                    "error": f"No CDR found for session_id {session_id}.",
                }

        url = urljoin(
            with_trailing_slash(settings.HUBJECT_URL),
            f"cdrmgmt/v22/operators/{operator_id}/charge-detail-record",
        )

        try:
            payload = (
                HubjectService.converter.convert_cdr_to_eroaming_charging_detail_record(
                    cdr
                )
            )
            payload_json = payload.model_dump(mode="json", exclude_none=True)
        except ValidationError as ve:
            return {
                "success": False,
                "errorType": "Validation Error",
                "error": str(ve),
            }

        retry_policy = dict(max_retries=retries, interval_start=5)
        send_hubject_request.apply_async(
            args=(payload_json, url, "post"), retry=True, retry_policy=retry_policy
        )
        return {
            "success": True,
            "message": "Sent CDR to hubject",
        }
