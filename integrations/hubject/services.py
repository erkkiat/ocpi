import logging
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
)
from integrations.solid_to_hubject_converter import SolidToHubjectConverter
from ocpi22.models.location import Location, Connector, Evse
from ocpiconnector.exceptions import ConnectorTariffNotFoundError
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
        response = {}

        try:
            payload_json = payload.model_dump_json()

            response = HubjectService.client.post(full_load_url, data=payload_json)
            logger.info("Logging hubject failure")
            logger.info("Full load url", full_load_url)
            logger.info("Type", type(payload_json))
            logger.info("Payload json", payload_json)
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
