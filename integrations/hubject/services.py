from collections import defaultdict
from typing import Dict, List
from urllib.parse import urljoin

from django.conf import settings

from integrations.hubject.client import HubjectClient
from integrations.hubject.schemas import (
    ERoamingPushEvseData,
    ActionType,
    OperatorEvseData,
)
from integrations.ocpi_to_hubject_converter import OCPIToHubjectConverter
from ocpi22.models.location import Location
from util import with_trailing_slash

import ocpi22.logging as logging


class HubjectService:
    client = HubjectClient()
    converter = OCPIToHubjectConverter()

    def get_operator_evse_dict(self):
        locations = Location.objects.all()

        collection: Dict[str, List] = defaultdict(list)
        for location in locations:
            op_evse_data = HubjectService.converter.convert_to_operator_evse_data(
                location
            )
            collection[op_evse_data.OperatorID.root].append(op_evse_data)

        return collection

    def get_evse_full_load_payload_by_operator_id(self, operator_id, op_evse_list):
        evse_list = [
            record for op_evse in op_evse_list for record in op_evse.EvseDataRecord
        ]

        return ERoamingPushEvseData(
            ActionType=ActionType.fullLoad,
            OperatorEvseData=OperatorEvseData(
                OperatorID=operator_id,
                OperatorName=op_evse_list[0].OperatorName
                if len(op_evse_list) > 0
                else "",
                EvseDataRecord=evse_list,
            ),
        )

    def execute_evse_full_load(self, operator_id, payload):
        full_load_url = urljoin(
            with_trailing_slash(settings.HUBJECT_URL),
            f"evsepush/v23/operators/{operator_id}/data-records",
        )

        response = None

        try:
            headers = {"Content-type": "application/json"}
            response = HubjectService.client.post(
                full_load_url, data=payload.model_dump_json(), headers=headers
            )
            return response.json()
        except Exception as exc:
            logging.error(exc)
            return response.json()
