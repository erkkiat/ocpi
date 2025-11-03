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
    result_backend = broker_url

    if os.environ.get("ENV") in {"production", "staging"}:
        _ssl_configuration = {"ssl_cert_reqs": ssl.CERT_NONE}
        broker_use_ssl = _ssl_configuration
        redis_backend_use_ssl = _ssl_configuration

    task_serializer = "orjson"
    accept_content = ["json", "orjson"]
    result_expires = 1
    worker_concurrency = 4
    task_time_limit = 300
    task_soft_time_limit = 240
    task_always_eager = strtobool(os.getenv("CELERY_TASK_ALWAYS_EAGER", "False"))
    task_ignore_result = True
    task_publish_retry = True
    task_publish_retry_policy = {
        "max_retries": 5,
        "interval_start": 0,
        "interval_step": 1,
        "interval_max": 5,
    }

    broker_connection_retry = True
    broker_connection_retry_on_startup = True
    broker_connection_max_retries = None

    broker_transport_options = {
        "socket_timeout": 30,
        "socket_connect_timeout": 30,
        "socket_keepalive": True,
        "retry_on_timeout": True,
        "health_check_interval": 30,
        "max_connections": 50,
    }

    result_backend_transport_options = {
        "socket_timeout": 30,
        "socket_connect_timeout": 30,
        "socket_keepalive": True,
        "retry_on_timeout": True,
        "health_check_interval": 30,
        "max_connections": 20,
    }

    broker_pool_limit = 20
    task_acks_late = True
    task_reject_on_worker_lost = True
    worker_prefetch_multiplier = 1
    worker_cancel_long_running_tasks_on_connection_loss = True
    worker_max_tasks_per_child = 1000


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
from ocpi22.cpo.session_service import SessionService  # noqa
from ocpi22.locations.services import EvseServices  # noqa
from ocpi22.models.location import Evse  # noqa
from ocpi22.models.session import Session  # noqa
from ocpi22.tasks import send_ocpi_request  # noqa
from integrations.hubject.schemas import ChargingNotificationType  # noqa
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


@shared_task(queue="HIGH")
def update_meter_values_async(
    session_id: str,
    timestamp: str,
    kwh: float,
    soc: float | None = None,
    power: float | None = None,
) -> None:
    try:
        session = (
            Session.objects.select_related(
                "credentials",
                "credentials__roles",
                "evse",
                "evse__location",
                "connector",
                "connector__tariff_ids",
            )
            .prefetch_related("chargingperiods__dimensions")
            .filter(uid=session_id)
            .first()
        )

        if not session:
            logger.warning(f"No session found for session_id: {session_id}")
            return

        if session.status != Session.ACTIVE:
            logger.info(
                f"Meter values received for non-active session: {session_id} "
                f"with status {session.status}, skipping"
            )
            return

        timestamp_dt = datetime.fromisoformat(timestamp)

        SessionService().update_meter_values(
            session=session,
            timestamp=timestamp_dt,
            kwh=kwh,
            soc=soc,
            power=power,
        )

        session.send_updates(
            method="put", update_type=ChargingNotificationType.Progress
        )

        logger.info(f"Successfully processed meter values for session {session_id}")

    except Exception:
        logger.warning(
            f"Failed to process meter values for session {session_id}. "
            f"Next meter value or stop_transaction will provide updated state.",
            exc_info=True,
        )
