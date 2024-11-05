from typing import List, Dict
from ninja import NinjaAPI
from integrations.hubject.services import HubjectService

api = NinjaAPI()


@api.post("/full-load/", url_name="hubject-evse-full-load")
# @api.post("/full_load/", url_name="hubject-evse-full-load", auth=JWTAuth())
# @permission_classes([IsAdminUser])
# @permission_required('is_admin', raise_exception=True)
def start_evse_full_load(request):
    service = HubjectService()
    collection: Dict[str, List] = service.get_operator_evse_dict()

    # Send all EVSEs for each operator
    for operator_id, op_evse_records in collection.items():
        # Create data payload
        payload = service.get_evse_full_load_payload_by_operator_id(
            operator_id, op_evse_records
        )
        service.execute_evse_full_load(operator_id, payload)

    return {
        "success": True,
        "message": "Successfully pushed the full load evses to Hubject",
    }
