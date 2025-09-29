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
    task_time_limit = 300
    task_soft_time_limit = 240
    task_always_eager = strtobool(os.getenv("CELERY_TASK_ALWAYS_EAGER", "False"))


# Todo: The tasks should be independent of Django, so we can run them in a separate process
app = Celery("mqtt_tasks", task_cls=RefreshTokenBaseTask)
app.conf.worker_hijack_root_logger = False
app.conf.task_queues = (
    Queue("HIGH", Exchange("HIGH"), routing_key="HIGH"),
    # Add other queues as needed
)
app.config_from_object(CeleryConfig)
app.conf.task_default_queue = "HIGH"
app.autodiscover_tasks()

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
    evse = Evse.objects.filter(uid=evse_uid, evse_id=evse_id).first()
    if not evse:
        logger.warning(f"Evse not found for uid:{evse_uid} and evse_id:{evse_id}")
        return
    status = EvseServices.ocpp_to_evse_status(status)
    evse.status = status
    evse.last_updated = datetime.now(ZoneInfo("UTC"))
    evse.save(update_fields=["status", "last_updated"])
    EvseServices.send_status_updates(evse)
    return
