from integrations.hubject.schemas import (
    ERoamingPushEvseData,
    ActionType,
    OperatorEvseData,
)
from integrations.ocpi_to_hubject_converter import OCPIToHubjectConverter
from ocpi22.models.location import Location
from django.conf import settings

import requests


class EroamingEvseDataPushApi:
    @staticmethod
    def full_load():
        locations = Location.objects.all()
        ocpi_to_hubject_converter = OCPIToHubjectConverter()

        collection = {}

        for location in locations:
            op_evse_data = ocpi_to_hubject_converter.convert_to_operator_evse_data(
                location
            )
            if op_evse_data.OperatorID.root in collection:
                collection[op_evse_data.OperatorID.root].append(op_evse_data)
            else:
                collection[op_evse_data.OperatorID.root] = [op_evse_data]

        for op in collection.keys():
            evses = []
            for op_data in collection[op]:
                evses.extend(op_data.EvseDataRecord)
            data_to_send = ERoamingPushEvseData(
                ActionType=ActionType.fullLoad,
                OperatorEvseData=OperatorEvseData(
                    OperatorID=collection[op][0].OperatorID,
                    OperatorName=collection[op][0].OperatorName,
                    EvseDataRecord=evses,
                ),
            )
            url = f"evsepush/v23/operators/{data_to_send.OperatorEvseData.OperatorID}/data-records"
            requests.post(
                f"{settings.HUBJECT_URL}{url}", json=data_to_send.model_json_schema()
            )
