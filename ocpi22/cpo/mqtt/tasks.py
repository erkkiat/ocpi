import os

from celery import shared_task, Celery
from django.db.models import F, Value
from django.db.models.functions import Concat

from ocpi22 import logging as logger
from ocpi22.choices import OcpiRolesEnum, CdrDimensionEnum
from ocpi22.cpo.session_cache import get_cached_session, store_session_cache
from ocpi22.models.location import Evse
from ocpi22.tasks import send_ocpi_request
from ocpiconnector.ocpi_identities import get_our_party
from util import format_session_url


# Todo: The tasks should be independent of Django, so we can run them in a separate process
class CeleryConfig:
    broker_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    result_backend = broker_url
    task_serializer = "json"
    accept_content = ["json"]
    result_expires = 1
    worker_concurrency = 4
    task_time_limit = 15
    task_soft_time_limit = 10
    task_always_eager = os.getenv("CELERY_ALWAYS_EAGER", "False")
    task_queue =




#
app = Celery('mqtt_tasks')
app.config_from_object(CeleryConfig)
import ipdb;ipdb.set_trace()
app.autodiscover_tasks()


@shared_task
def process_meter_values(session_id, internal_reference, kwh, soc, power, timestamp):
    session_id = session_id or internal_reference
    # timestamp = meter_values.timestamp or datetime.now(pytz.utc)

    session = get_cached_session(session_id)
    session.kwh = kwh
    store_session_cache(session)

    route = session.route_to_msp
    if not route:
        logger.error(f"Route not found for session {session_id}")
        return
    # print(f"{route=}, {session_id=}, {timestamp=}, {meter_values=}")
    print(f"{kwh=} {route=}")
    data = dict(
        kwh=kwh,
        last_updated=timestamp,
        total_cost=dict(
            incl_vat=0,
            excl_vat=0,
        ),  # Todo: Calculate the cost based on SolidTariff
        charging_periods=[
            {
                "start_date_time": timestamp,
                "dimensions": [
                    {
                        "type": CdrDimensionEnum.ENERGY.value,
                        "volume": kwh
                    },
                    # {
                    #     "type": CdrDimensionEnum.POWER.value,
                    #     "volume": power  # Todo: should be average power during the period
                    # },
                    # {
                    #     "type": CdrDimensionEnum.STATE_OF_CHARGE.value,
                    #     "volume": soc
                    # },
                ]
            }
        ]
    )

    our_party = get_our_party(role=OcpiRolesEnum.CPO)

    # Todo: Should we send the request async and update the session to the database while we wait?
    #   We need it if the MSP tries to pull the full session objects

    url = format_session_url(route.url, our_party.country_code, our_party.party_id, session_id)
    receiver = session.route_to_msp.to

    # send_ocpi_request.delay(data, url=route.url, token_base64=route.token_base64,
    send_ocpi_request(data, url=url, token_base64=route.token_base64,
                      to_country_code=receiver.country_code, to_party_id=receiver.party_id,
                      from_country_code=our_party.country_code, from_party_id=our_party.party_id,
                      credentials_id=route.credentials_id,
                      method='patch')

    # To write Django model instances to the database asynchronously, you can leverage
    # the asynchronous capabilities introduced in Django 4.1 and later versions.
    # Django’s ORM now provides asynchronous methods like acreate(), asave(), and aupdate()
    # for performing database operations without blocking the event loop.


def _get_evse_by_uid(uid: str): # TODO: Move this to the corresponding repository
    evse = (
        Evse.objects
        .filter(uid=uid)  # Filter by UID
        .annotate(
            generated_evse_id=Concat(
                F('location__ocpi_master__country_code'),  # Country code from ocpi_master
                Value('*'),
                F('location__ocpi_master__party_id'),  # Party ID from ocpi_master
                Value('*E'),
                F('uid')  # UID from Evse
            )
        )
        .filter(generated_evse_id=F('evse_id'))  # Compare generated evse_id with the stored evse_id
        .select_related('location__ocpi_master')  # Optimize fetching related objects
        .first()
    )
    if not evse:
        raise logger.error(f"Evse with UID {uid} not found")


@shared_task
def save_and_send_evse_status_updates(evse_uid: str, status: str, last_updated: str) -> None:
    evse = _get_evse_by_uid(evse_uid)
    evse.status = status
    evse.last_updated = last_updated
    evse.save(update_fields=["status", "last_updated"])
    evse.send_status_updates()
    print("And done status")
    return
