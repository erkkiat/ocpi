from collections import defaultdict
from typing import List, Dict
from ninja import NinjaAPI

from integrations.hubject.services import HubjectService

api = NinjaAPI()


@api.post("/evses/full-load/", url_name="hubject-evse-full-load", response=Dict)
def update_oicp_evses_of_all_operators(request):
    service = HubjectService()
    operator_id_operator_evse_data_collection: Dict[str, List] = (
        service.get_operator_evse_dict()
    )
    hubject_responses = defaultdict(list)

    # Send all EVSEs for each operator
    for (
        operator_id,
        op_evse_records,
    ) in operator_id_operator_evse_data_collection.items():
        # Create data payload
        payload = service.get_evse_full_load_payload_by_operator_id(
            operator_id, op_evse_records
        )
        response = service.post_evse_full_load(operator_id, payload)

        hubject_responses[operator_id].append(response)

    return {
        "responses": hubject_responses,
    }
