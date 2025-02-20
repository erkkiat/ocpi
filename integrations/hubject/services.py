import logging
from collections import defaultdict
from urllib.error import HTTPError
from urllib.parse import urljoin

from django.conf import settings
from django.db.models import Prefetch
from pydantic_core import PydanticSerializationError

from integrations.hubject.client import HubjectClient
from integrations.hubject.schemas import (
    ERoamingPushEvseData,
    ActionType,
    OperatorEvseData,
    PricingProductData,
    ERoamingPushPricingProductData,
    ERoamingPushEVSEPricing,
    HubjectPriceComponent,
    ProductID,
    ProviderIDAsterisk,
    EVSEPricingItem,
)
from integrations.solid_to_hubject_converter import SolidToHubjectConverter
from integrations.hubject.schemas import HubjectDefaultTariff
from ocpi22.choices import OcpiRolesEnum
from ocpi22.models.location import Location, Connector, Evse
from ocpi22.models.tariff import SolidTariff, Tariff
from ocpiconnector.exceptions import ConnectorTariffNotFoundError
from ocpiconnector.ocpi_identities import get_our_identity
from ocpiconnector.party import Party
from util import with_trailing_slash

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class HubjectService:
    client = HubjectClient()
    converter = SolidToHubjectConverter()

    def get_operator_evse_data(self, party: Party) -> OperatorEvseData | None:
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
            OperatorID=str(party),
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

    def post_evse_full_load(
        self, operator_id: str, payload: ERoamingPushEvseData
    ) -> dict:
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
            raise ValueError(f"No SolidTariffs found for {str(party)}")

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

    def get_evse_product_provider_maps(self, party: Party) -> defaultdict:
        evses = Evse.objects.filter(
            location__ocpi_master__country_code=party.country_code,
            location__ocpi_master__party_id=party.party_id,
        ).prefetch_related(
            Prefetch(
                "connectors",
                queryset=Connector.objects.prefetch_related(
                    Prefetch("tariff_ids", queryset=Tariff.objects.only("uid"))
                ),
                to_attr="connectors_with_tariffs",
            )
        )

        all_tariff_uids = {
            tariff.uid
            for evse in evses
            for connector in evse.connectors_with_tariffs
            for tariff in connector.tariff_ids.all()
        }

        solid_tariffs = (
            SolidTariff.objects.filter(external_id__in=all_tariff_uids)
            .select_related("msp")
            .values(
                "external_id",
                "price_per_kwh",
                "price_per_min",
                "msp__country_code",
                "msp__party_id",
            )
        )

        solid_tariff_map = defaultdict(list)
        for solid_tariff in solid_tariffs:
            solid_tariff_map[solid_tariff["external_id"]].append(solid_tariff)

        party_str = str(party)
        evse_pricing_product_id_provider_id_map = defaultdict(lambda: [[], []])

        for evse in evses:
            for connector in evse.connectors_with_tariffs:
                tariff_uids = {tariff.uid for tariff in connector.tariff_ids.all()}
                print(tariff_uids)
                related_solid_tariffs = [
                    solid_tariff
                    for uid in tariff_uids
                    for solid_tariff in solid_tariff_map.get(uid, [])
                ]

                for solid_tariff in related_solid_tariffs:
                    if not solid_tariff.get("msp__country_code"):
                        logger.info(
                            f"No MSP found for SolidTariff {solid_tariff.get('external_id')}"
                        )
                        continue

                    for component, has_price in [
                        (HubjectPriceComponent.KWH, solid_tariff["price_per_kwh"]),
                        (HubjectPriceComponent.MINUTE, solid_tariff["price_per_min"]),
                    ]:
                        if has_price:
                            pricing_product_id = self.converter.get_pricing_product_id(
                                solid_tariff.get("external_id"),
                                component,
                                party_str,
                                f"{solid_tariff['msp__country_code']}*{solid_tariff['msp__party_id']}",
                            )

                            evse_pricing_product_id_provider_id_map[evse.evse_id][
                                0
                            ].append(ProductID(root=pricing_product_id))
                            evse_pricing_product_id_provider_id_map[evse.evse_id][
                                1
                            ].append(
                                ProviderIDAsterisk(
                                    root=f"{solid_tariff['msp__country_code']}*{solid_tariff['msp__party_id']}"
                                )
                            )

        return evse_pricing_product_id_provider_id_map

    def get_evse_pricing_product_data_full_load_payload(
        self, evse_product_id_provider_id_map: dict
    ) -> ERoamingPushEVSEPricing:
        evse_pricing_items = []
        for evse_id, tariff_id_msp_list in evse_product_id_provider_id_map.items():
            evse_pricing_items.append(
                EVSEPricingItem(
                    EvseID=evse_id,
                    # todo: According to Mike we should have a list here. But as of now a list is not accepted by hubject
                    ProviderID=tariff_id_msp_list[1][0],
                    EvseIDProductList=tariff_id_msp_list[0],
                )
            )

        return ERoamingPushEVSEPricing(
            ActionType=ActionType.fullLoad, EVSEPricing=evse_pricing_items
        )

    def post_evse_pricing_item_full_load(
        self, operator_id: str, payload: ERoamingPushEVSEPricing
    ):
        full_load_url = urljoin(
            with_trailing_slash(settings.HUBJECT_URL),
            f"dynamicpricing/v10/operators/{operator_id}/evse-pricing",
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
                "error": str(e),
            }
        except HTTPError as exc:
            logging.error(exc)
            return {
                "success": False,
                "errorType": "HTTP request failed",
                "error": str(exc),
            }
