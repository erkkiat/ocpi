import os
import ssl
from datetime import datetime
from distutils.util import strtobool
from enum import Enum
from logging import getLogger
from zoneinfo import ZoneInfo

import orjson
from celery import shared_task, Celery
from kombu import Queue, Exchange
from kombu.serialization import register
from base_task_services import RefreshTokenBaseTask

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ocpiconnector.settings.dev")
import django

django.setup()


def custom_orjson_dumps(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"Type {type(obj)} is not serializable")


def orjson_serializer(obj):
    return orjson.dumps(obj, default=custom_orjson_dumps).decode()


register(
    "orjson",
    orjson_serializer,
    orjson.loads,
    content_type="application/json",
    content_encoding="utf-8",
)


class CeleryConfig:
    broker_url = os.environ["REDIS_URL"]
    # a bit hack but will refactor after it is working

    if os.environ["ENV"] in ["production", "staging"]:
        _ssl_configuration = {
            "ssl_cert_reqs": ssl.CERT_NONE,
        }
        redis_backend_use_ssl = _ssl_configuration
    result_backend = broker_url
    task_serializer = "orjson"
    accept_content = ["json"]
    result_expires = 1
    worker_concurrency = 4
    task_time_limit = 15
    task_soft_time_limit = 10
    task_always_eager = strtobool(os.getenv("CELERY_TASK_ALWAYS_EAGER", "False"))


# Todo: The tasks should be independent of Django, so we can run them in a separate process
app = Celery("mqtt_tasks", task_cls=RefreshTokenBaseTask)
app.conf.task_queues = (
    Queue("HIGH", Exchange("HIGH"), routing_key="HIGH"),
    # Add other queues as needed
)
app.config_from_object(CeleryConfig)
app.conf.task_default_queue = "HIGH"
app.autodiscover_tasks()

from base_task_services import setup_worker_connection  # noqa
from rest_framework.generics import get_object_or_404  # noqa

from ocpi22.choices import OcpiRolesEnum, CdrDimensionEnum  # noqa
from ocpi22.cpo.mqtt.custom_orjson_serializer import orjson_serializer  # noqa
from ocpi22.cpo.session_cache import get_cached_session, store_session_cache  # noqa
from ocpi22.locations.services import EvseServices  # noqa
from ocpi22.models.location import Evse  # noqa
from ocpi22.models.session import Session  # noqa
from ocpi22.tasks import send_ocpi_request  # noqa
from ocpiconnector.ocpi_identities import get_our_party  # noqa
from util import format_session_url  # noqa

logger = getLogger(__name__)


@shared_task(queue="HIGH")
def process_meter_values(session_id, kwh, soc, power, timestamp):
    session = Session.get_if_exists(uid=session_id, raise_exception=True)
    session.stop_kwh = kwh
    session.last_updated = timestamp
    session.save(update_fields=["stop_kwh", "last_updated"])

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
                    {"type": CdrDimensionEnum.ENERGY.value, "volume": kwh},
                    # {
                    #     "type": CdrDimensionEnum.POWER.value,
                    #     "volume": power  # Todo: should be average power during the period
                    # },
                    # {
                    #     "type": CdrDimensionEnum.STATE_OF_CHARGE.value,
                    #     "volume": soc
                    # },
                ],
            }
        ],
    )

    our_party = get_our_party(role=OcpiRolesEnum.CPO)

    # Todo: Should we send the request async and update the session to the database while we wait?
    #   We need it if the MSP tries to pull the full session objects

    url = format_session_url(
        route.url, our_party.country_code, our_party.party_id, session_id
    )
    receiver = session.route_to_msp.to

    # send_ocpi_request.delay(data, url=route.url, token_base64=route.token_base64,
    send_ocpi_request(
        data,
        url=url,
        token_base64=route.token_base64,
        to_country_code=receiver.country_code,
        to_party_id=receiver.party_id,
        from_country_code=our_party.country_code,
        from_party_id=our_party.party_id,
        credentials_id=route.credentials_id,
        method="patch",
    )

    # To write Django model instances to the database asynchronously, you can leverage
    # the asynchronous capabilities introduced in Django 4.1 and later versions.
    # Django’s ORM now provides asynchronous methods like acreate(), asave(), and aupdate()
    # for performing database operations without blocking the event loop.


def _get_country_and_party_id():
    cpo = os.getenv("CPO")
    if not cpo:
        raise ValueError("CPO is not set in the environment variables")
    return cpo.split("*")


def _format_evse_id(country_code: str, party_id: str, evse_uid: str) -> str:
    return f"{country_code}*{party_id}*E{evse_uid}"


@shared_task(queue="HIGH")
def save_and_send_evse_status_updates(evse_uid: str, status: str) -> None:
    country, party_id = _get_country_and_party_id()
    evse_id = _format_evse_id(country, party_id, evse_uid)
    evse = get_object_or_404(Evse, uid=evse_uid, evse_id=evse_id)
    status = EvseServices.ocpp_to_evse_status(status)
    evse.status = status
    evse.last_updated = datetime.now(ZoneInfo("UTC"))
    evse.save(update_fields=["status", "last_updated"])
    evse.send_status_updates()
    return
