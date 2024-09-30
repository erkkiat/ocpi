import os
from datetime import datetime
from typing import Optional

from cachetools import cached, TTLCache
import pytz
from celery import shared_task, Celery

from ocpi22 import logging
from ocpi22.choices import OcpiModuleEnum
from ocpi22.cpo.mqtt.schemas import CachedSession
from ocpi22.routing import Route
from ocpiconnector.party import Party
from util import OCPIVersion


class CeleryConfig:
    broker_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    # result_backend = "redis://localhost:6379/0"
    task_serializer = "orjson"
    accept_content = ["json"]
    result_expires = 1
    worker_concurrency = 4

    # Todo: @Aurora Should we have one celery thread per partner? Then the slower ones would not block the faster ones
    task_time_limit = 15
    task_soft_time_limit = 10


app = Celery('mqtt_tasks')
app.config_from_object(CeleryConfig)


def get_cached_session(session_id) -> CachedSession:
    # Todo: Implement session caching in start_session
    route = Route(to=Party("BE", "SMP"), identifier=OcpiModuleEnum.SESSIONS, token_base64="1234567890",
                  url="http://localhost:8002/ocpi/cpo/2.2/sessions/1234567890",
                  credentials_id=1, alive=True, direct=True, version=OCPIVersion("221"))
    return CachedSession(session_id=session_id,
                         kwh=10, timestamp=datetime.now(pytz.utc),
                         route_to_msp=route)


@cached(cache=TTLCache(maxsize=0, ttl=4*60*60))
def find_route_by_session(session_id) -> Optional[Route]:
    """
    The session should be cached in Redis during the start_session() call
    No time to read or write Session objects through Django ORM, let's use Redis instead
    This function is cached locally to reduce calls to the managed Redis instance, since all calls incur cost
    """
    session = get_cached_session(session_id)
    return getattr(session, "route_to_msp", None)


@shared_task
def process_meter_values(session_id, internal_reference, kwh, soc, power, timestamp):
    session_id = session_id or internal_reference
    # timestamp = meter_values.timestamp or datetime.now(pytz.utc)

    route = find_route_by_session(session_id)
    if not route:
        logging.error(f"Route not found for session {session_id}")
        return
    # print(f"{route=}, {session_id=}, {timestamp=}, {meter_values=}")
    print(f"{kwh=}")
    # We may or may not have time to update the session on Redis or SQL, let's do some perfomance testing first
