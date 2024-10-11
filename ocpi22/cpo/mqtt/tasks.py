import os
from datetime import datetime
from typing import Optional

from cachetools import cached, TTLCache
from celery import shared_task, Celery
from django.conf import settings

from ocpi22 import logging
from ocpi22.choices import OcpiRolesEnum
from ocpi22.cpo.mqtt.schemas import CachedSession
from ocpi22.routing import Route
from ocpi22.tasks import send_ocpi_request
from ocpiconnector.ocpi_identities import get_our_party
from util import RedisStore


# Todo: The tasks should be independent of Django, so we can run them in a separate process

class CeleryConfig:
    broker_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    result_backend = broker_url
    task_serializer = "orjson"
    accept_content = ["json"]
    result_expires = 1
    worker_concurrency = 4
    task_time_limit = 15
    task_soft_time_limit = 10


app = Celery('mqtt_tasks')
app.config_from_object(CeleryConfig)

session_cache = RedisStore(namespace=settings.REDIS_SESSION_CACHE_NAMESPACE)


def get_cached_session(session_id) -> CachedSession:
    # Todo: Implement session caching in start_session
    return session_cache.retrieve(session_id)


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
    print(f"{kwh=} {route=}")
    data = dict(
        kwh=kwh,
        last_updated=timestamp,
        total_cost=123,  # Todo: Calculate the cost
        # charging_periods=...,  # Needed for power and soc
    )

    our_party = get_our_party(role=OcpiRolesEnum.CPO)

    # Todo: Should we send the request async and update the session to the database while we wait?
    #   We need it if the MSP tries to pull the full session objects

    # send_ocpi_request.delay(data, url=route.url, token_base64=route.token_base64,
    send_ocpi_request(data, url=route.url, token_base64=route.token_base64,
                      to_country_code=route.to.country_code, to_party_id=route.to.party_id,
                      from_country_code=our_party.party_id, from_party_id=our_party.party_id,
                      credentials_id=route.credentials_id,
                      method='patch')

    # To write Django model instances to the database asynchronously, you can leverage
    # the asynchronous capabilities introduced in Django 4.1 and later versions.
    # Django’s ORM now provides asynchronous methods like acreate(), asave(), and aupdate()
    # for performing database operations without blocking the event loop.
