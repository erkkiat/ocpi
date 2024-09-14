from datetime import datetime

from ninja import NinjaAPI

from django.conf import settings
from ninja_extra.permissions import IsAdminUser
from ninja_jwt.authentication import JWTAuth
from rest_framework.decorators import permission_classes

from fastapi.celery.tasks import activate_session
from fastapi.mongodb.connection import meter_values_col
from ocpi22.models.location import Connector
from fastapi.schemas.charging import MeterValuesSchema, StopSchema, StartSchema
from ocpi22.tokens.auth import get_session_by_adhoc_token, authorize_token

api = NinjaAPI(urls_namespace='charging')


@api.post("/meter_values/", url_name="chargepoint-meter-values", auth=JWTAuth())
@permission_classes([IsAdminUser])
# @silk_profile(name='chargepoint_meter_values')
def chargepoint_meter_values(request, payload: MeterValuesSchema):
    # ic(request.user, payload)
    data = payload.model_dump()
    # ic(data)
    data['datestamp'] = int((payload.datestamp or datetime.utcnow()).timestamp())
    # ic(data)
    x = meter_values_col.insert_one(data)
    ic(x.inserted_id)
    return {"status": "success"}


@api.post("/start/", url_name="chargepoint-start-transaction", response={200: dict, 400: dict})  # auth=JWTAuth(),
# @silk_profile(name='chargepoint_start_transaction')
# @permission_classes([IsAdminUser])
def chargepoint_start_transaction(request, payload: StartSchema):
    ic(request.user, payload)
    session = get_session_by_adhoc_token(payload.token_id, max_age_minutes=15)
    # ic(bool(session))
    if not session:
        return 400, {"status": "error", "message":
            "Token needs to be authorized within 15 minutes before starting a session."}
        # connector = Connector.objects.select_related('evse__location').order_by('-created'). \
        #     get_if_exists(uid__iexact=payload.connector_id, evse__uid__iexact=payload.evse_uid, raise_exception=True,
        #                   multiple_is_ok_just_get_the_first_one=True)
        # authorization = authorize_token(payload.token_id, location=connector.evse.location, request=request, max_age=0,
        #                                 rfid=True)
        # assert authorization.allowed
        # raise NotImplementedError()

    # Todo: Start the session on Celery, here we just need to return the existing session_id for the session
    #  which needs to be created already during SESSION_START
    #  (or maybe we should just set the Session active here, since it's only one SQL query?)
    activate_session.delay(session)
    ic(session)
    return {"session": dict(session_id=session.uid)}


@api.post("/stop/", url_name="chargepoint-stop-transaction", auth=JWTAuth())
# @silk_profile(name='chargepoint_stop_transaction')
@permission_classes([IsAdminUser])
def chargepoint_stop_transaction(request, payload: StopSchema):
    # ic(request.user, payload)
    # ic(list(meter_values_col.find(dict(session_id=payload.session_id))))
    print(f'Stopping session {payload.session_id} with {payload.stop_kwh} kWh')
    return {"status": "success"}
