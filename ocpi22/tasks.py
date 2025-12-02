import os
import random
import ssl
from datetime import timedelta, datetime
from functools import lru_cache
from logging import getLogger
from typing import Literal
from urllib.parse import urlparse

import celery
import pytz
import requests
from json import JSONDecodeError

from celery import shared_task
from celery.schedules import crontab
from django.conf import settings
from django.http import HttpRequest
from django.utils.module_loading import import_string
from pydantic import ValidationError
from requests import Response, RequestException
from requests.auth import HTTPBasicAuth
from rest_framework import status

from base_task_services import RefreshTokenBaseTask
from ocpi22 import choices
from ocpi22.choices import OcpiRolesEnum
from ocpi22.ocpi.headers import make_headers
from ocpi22.ssl_services import load_ssl_context, SSLAdapter
from ocpiconnector.exceptions import ConnectorTariffNotFoundError
from ocpiconnector.ocpi_identities import get_our_party
from ocpiconnector.party import Party
from ocpiconnector.settings import setup_sentry
from util import unwrap

logger = getLogger(__name__)

setup_sentry()
# Set the default Django settings module for the 'celery' program.
if "DJANGO_SETTINGS_MODULE" not in os.environ:
    os.environ["DJANGO_SETTINGS_MODULE"] = "ocpiconnector.settings"

RESULT_EXPIRE_TIME = os.environ.get(
    "RESULT_EXPIRE_TIME", 1
)  # 1 second, we don't need the results of the tasks

app = celery.Celery(
    "ocpi22.tasks", task_cls=RefreshTokenBaseTask, result_expires=RESULT_EXPIRE_TIME
)

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")
# app.conf.task_default_queue = "celery-django-mid"

pull_hour = random.randint(0, 3)
pull_minute = random.randint(0, 59)

app.conf.beat_schedule = {
    "run-me-every-minute": {
        "task": "ocpi22.tasks.celery_heartbeat",
        "schedule": 60 * 60,
    },
    "still-alive": {
        "task": "ocpi22.tasks.check_still_alive",
        "schedule": settings.STILL_ALIVE_FREQUENCY,
    },
    "pull-all-objects": {
        "task": "ocpi22.tasks.pull_all_objects",
        # 'schedule': 120  # For testing
        "schedule": crontab(hour=str(pull_hour), minute=str(pull_minute)),
    },
    "weekly-hubject-evse-full-load": {
        "task": "ocpi22.tasks.send_hubject_evse_full_load",
        "schedule": crontab(
            hour="2", minute="0", day_of_week="0"
        ),  # Every Sunday at 02:00AM
    },
}


@app.task
def celery_heartbeat() -> bool:
    return True


@shared_task(max_retries=3, retry_backoff=3600)
def pull_all_objects() -> bool:
    from ocpi22.models.credentials import Credentials  # noqa
    from ocpi22.pull import schedule_full_update

    credentials = Credentials.objects.filter(valid=True)
    for c in credentials:
        schedule_full_update(c)
    return True


# Make sure Redis is available
REDIS_URL = settings.REDIS_URL
assert (
    settings.DEBUG or REDIS_URL
), f"One of these keys needs to be set at least in the production: {settings.REDIS_KEYS}"
if "rediss" in REDIS_URL and "ssl_cert_reqs" not in REDIS_URL:
    REDIS_URL += "?ssl_cert_reqs=CERT_NONE"

if REDIS_URL:
    app.conf.update(broker_url=REDIS_URL, result_backend=REDIS_URL)

    app.conf.update(
        broker_connection_retry=True,
        broker_connection_retry_on_startup=True,
        broker_connection_max_retries=None,
        task_publish_retry=True,
        task_publish_retry_policy={
            "max_retries": 5,
            "interval_start": 0,
            "interval_step": 1,
            "interval_max": 5,
        },
        broker_transport_options={
            "socket_timeout": 30,
            "socket_connect_timeout": 30,
            "socket_keepalive": True,
            "retry_on_timeout": True,
            "health_check_interval": 30,
            "max_connections": 50,
        },
        result_backend_transport_options={
            "socket_timeout": 30,
            "socket_connect_timeout": 30,
            "socket_keepalive": True,
            "retry_on_timeout": True,
            "health_check_interval": 30,
            "max_connections": 20,
        },
        broker_pool_limit=20,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        worker_cancel_long_running_tasks_on_connection_loss=True,
        worker_max_tasks_per_child=1000,
        task_ignore_result=True,
    )

    # Load task modules from all registered Django apps.
    app.autodiscover_tasks()
else:
    logger.error(f"{settings.HOSTNAME}: REDIS_URL not set, no connection to REDIS")


def get_cert_from_env(var_name: str) -> str | None:
    val = os.getenv(var_name, None)
    if not val:
        return
    return val.replace("\\n", "\n").strip()


@lru_cache(maxsize=128)
def get_certificate_loaded_request(credential_id):
    from ocpi22.models.credentials import Credentials  # noqa

    credentials = Credentials.objects.filter(id=credential_id).first()
    if credentials:
        logger.info(f"Getting certificates for credentials for {credentials.id}")
        ca_cert = get_cert_from_env(credentials.ca_certificate_name)
        private_key = get_cert_from_env(credentials.private_key_name)
        client_cert = get_cert_from_env(credentials.client_certificate_name)
    else:
        logger.info(f"No credentials found for {credential_id}, setting empty string")
        client_cert = private_key = ca_cert = ""

    if not all([client_cert, private_key, ca_cert]):
        logger.warning(
            f"Missing one or more certificates. for credentials {credential_id}"
        )
        return requests.Session()
    logger.info(f"Creating SSL session client for {credential_id}")
    return _get_ssl_session_client(client_cert, private_key, ca_cert)


def _get_ssl_session_client(
    client_cert: str, private_key: str, ca_cert: str, verify_ssl=True
) -> requests.Session:
    ssl_context = load_ssl_context(client_cert, private_key, ca_cert, verify_ssl)

    session = requests.Session()
    if ssl_context:
        session.mount("https://", SSLAdapter(ssl_context=ssl_context))
    return session


@shared_task(
    bind=True,
    retry_backoff=1,
    max_retries=10,
)
def send_ocpi_request(
    self,
    data,
    url: str,
    token_base64: str,
    to_country_code: str,
    to_party_id: str,
    from_country_code: str,
    from_party_id: str,
    method: str = "put",
    credentials_id=None,
    title=None,
    **kwargs,
) -> Response | None:
    to = Party(to_country_code, to_party_id)
    sender = Party(from_country_code, from_party_id)

    headers = make_headers(token_base64, to=to, sender=sender)

    if isinstance(data, dict):
        kwargs.update(dict(url=url, json=data, headers=headers))
    else:
        kwargs.update(dict(url=url, data=data, headers=headers))

    try:
        request_session = get_certificate_loaded_request(credentials_id)
    except ssl.SSLError:
        logger.exception(f"SSL error while connecting to {url}.")
        # Don't retry on SSL errors as they're likely configuration issues
        return None

    function = getattr(request_session, method.lower())
    if not function:
        raise NotImplementedError(
            f"Method {method} is not supported for send_ocpi_request"
        )

    logger.info(f"Sending ocpi {method} request to {url} for {credentials_id}")
    response: requests.Response = function(**kwargs)
    if self.request.is_eager:
        return response
    if response.status_code < 300:
        try:
            response_json = response.json()
        except JSONDecodeError:
            response_json = {}
        status_code = response_json.get("status_code", 1000)
        status_message = response_json.get("status_message", "")
        if status_code >= 2000:
            logger.error(
                f"{url} responded with OCPI error code {status_code}: {status_message}, not retrying",
                extra={
                    "path": url,
                    "method": response.request.method,
                    "response_data": response_json or response.text,
                    "status_code": response.status_code,
                },
            )
            return
    if 300 <= response.status_code < 500:
        logger.error(
            f"{url} responded with {response.status_code}, not retrying",
            extra={
                "path": url,
                "method": response.request.method,
                "response_data": response.text,
                "status_code": response.status_code,
            },
        )
        return
    if response.status_code >= 500:
        logger.warning(f"Got {response.status_code} for {response.url}: Retrying")
        raise self.retry(
            exc=Exception(f"Server Error for {response.url}: {response.status_code}")
        )


@shared_task(
    bind=True,
    retry_backoff=1,
    max_retries=3,
)
def send_hubject_request(
    self,
    payload_json,
    url: str,
    method: Literal["get", "post", "put", "patch", "delete"] = "put",
) -> dict | None:
    try:
        from integrations.hubject.services import HubjectService

        logger.info(f"Sending hubject {method} request to {url}")
        response = HubjectService.client.session.request(
            method=method,
            url=url,
            json=payload_json,
            timeout=settings.HUBJECT_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            from integrations.hubject.schemas import ERoamingAcknowledgment

            try:
                ack = ERoamingAcknowledgment.model_validate(response.json())
                if not ack.result:
                    logger.error(
                        f"Hubject responded with negative acknowledgment for {url}",
                        extra={
                            "path": url,
                            "method": response.request.method,
                            "response_data": ack,
                            "status_code": response.status_code,
                        },
                    )
            except ValidationError:
                logger.error(
                    f"Validation error when parsing Hubject acknowledgment for {url}",
                    extra={
                        "path": url,
                        "method": response.request.method,
                        "response_data": response.text,
                        "status_code": response.status_code,
                    },
                )
        if self.app.conf.task_always_eager:
            return response.json() if response.text else None
        retry_count = self.request.retries
        if response.status_code >= 500:
            logger.warning(
                f"Hubject responded {response.status_code} for {response.url}: Retrying({retry_count})"
            )
            raise self.retry(
                exc=Exception(
                    f"Server Error for {response.url}: {response.status_code}"
                )
            )
        if response.status_code >= 400:
            logger.warning(
                f"Got {response.status_code} for {response.url}: {response.json()}"
            )
    except RequestException as e:
        retry_count = self.request.retries
        logger.warning(f"Request failed for {url}")
        if retry_count < self.max_retries:
            raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3, retry_backoff=60)
def send_hubject_evse_full_load(self) -> None:
    from integrations.hubject.services import HubjectService

    try:
        our_party = get_our_party(OcpiRolesEnum.CPO)
        service = HubjectService()
        try:
            payload = service.get_evse_full_load_payload(our_party)

            if payload is None:
                logger.warning(
                    f"Failed to create payload for {str(our_party)} during Hubject EVSE FullLoad. No EVSE/location data available",
                )
                return
        except ConnectorTariffNotFoundError:
            return

        HubjectService.post_evse_full_load(str(our_party), payload)

    except Exception as exc:
        logger.exception(f"Error updating OICP EVSEs for {str(our_party)}")
        raise self.retry(exc=exc, countdown=60)


@shared_task(max_retries=2, retry_backoff=2)
def exchange_credentials(token, url):
    from ocpiconnector.management.commands import exchange_credentials

    command = exchange_credentials.Command()
    command.handle(token_a=token, versions_endpoint_url=url)


@shared_task(max_retries=2, retry_jitter=True, retry_backoff=120)
def pull_objects(
    object_list, limit=10, delay=2, total_objects=0, credentials_id=None, **kwargs
) -> None:
    assert isinstance(
        credentials_id, int
    ), f"credentials_id is missing: {credentials_id}"
    from ocpi22.models.credentials import Credentials  # noqa

    credentials = Credentials.objects.get(pk=credentials_id)

    try:
        if not object_list:
            logger.info("Empty object list, nothing to pull")
            return
        next_url = ""
        obj = object_list[0]
        url = kwargs.pop("url", obj.get("url", ""))
        if url:
            if "limit=" not in url:
                url = f"{url}?limit={limit}"
            response = send_ocpi_request(data=dict(), url=url, **kwargs)
            if response and response.status_code < 300:
                next_url, _rel = (
                    response.headers.get("Link", ";").strip("<>").split(";")
                )
                model = obj.get("model")
                viewset = import_string(obj.get("viewset"))
                items = response.json().get("data", [])
                total_objects += len(items)
                for i in items:
                    try:
                        # TODO: Check that party matches with Credentials, don't allow third party data
                        request = HttpRequest()
                        request.party_specified_in_url = True
                        party = Party(i.get("country_code"), i.get("party_id"))
                        if not party:
                            logger.error(
                                f"Trying to pull data from {credentials}, "
                                f"but unable to determine party for {i}"
                            )
                            continue
                        if credentials.is_hub:
                            # We accept data owned by any party if pulling from a hub
                            from ocpi22.ocpi.auth import get_credentialsrole

                            credentialsrole = get_credentialsrole(
                                credentials=None, party=party
                            )
                        else:
                            # Not pulling from a hub, so the Credentials party must match
                            credentialsrole = credentials.roles.first()
                            if credentialsrole.get_party() != party:
                                logger.error(
                                    f"Party {party} in the pulled data doesn't match party "
                                    f"{credentialsrole.party_str()} in the credentialsrole. "
                                    "The other party may be spoofing a location of another operator."
                                )
                                continue

                        # Check if we have pulled our own object
                        from ocpi22.util import is_our_identifier

                        if is_our_identifier(credentialsrole.get_party()):
                            logger.info(
                                f"Party {party} in the pulled data matches our own party, not storing."
                            )
                            continue

                        # Unwrap the decorated put function so that we can provide the suitable parameters directly
                        func = unwrap(viewset.put)
                        response = func(
                            viewset(),
                            request=None,
                            data=i,
                            credentialsrole=credentialsrole,
                        )
                        if response.status_code >= status.HTTP_400_BAD_REQUEST:
                            raise Exception(
                                response.data.get(
                                    "status_message", "<no status message provided>"
                                )
                            )
                    except Exception:
                        logger.exception(
                            f"Unable to update {model} using data pulled from url {url} "
                            f"for uid {i.get('uid', i.get('id', ''))}"
                        )
                        raise
                if next_url:
                    kwargs["url"] = next_url

        if not next_url:
            object_list.pop(0)
            if not len(object_list):
                logger.info(f"Total of {total_objects} objects pulled")
                return

        countdown = random.randint(delay, int(1.5 * delay))

        if settings.BACKGROUND_SEND:
            pull_objects.apply_async(
                (object_list, limit, delay, total_objects, credentials_id),
                kwargs=kwargs,
                countdown=countdown,
            )
        else:
            pull_objects(
                object_list, limit, delay, total_objects, credentials_id, **kwargs
            )
    except RequestException:
        logger.exception("Unable to pull objects")


@shared_task(max_retries=0)  # We will do this every 5 minutes anyways
def check_still_alive(credentials_id: int = None) -> None:
    from ocpi22.models.credentials import Credentials  # noqa

    if credentials_id:
        credentials = Credentials.objects.none()
        time_since_last_connection = 0
        try:
            credentials: Credentials = Credentials.objects.get(pk=credentials_id)
            if credentials.last_connection:
                time_since_last_connection = (
                    datetime.now(pytz.utc) - credentials.last_connection
                ).total_seconds()
            requests.get(credentials.url, timeout=20)
            credentials.last_connection = datetime.now(pytz.utc)
            credentials.connection_status = choices.CONNECTED
            logger.info(f"{credentials} is alive")
        except IOError:
            logger.exception(
                f"{credentials} is *NOT* alive ({credentials.url}), "
                f"last connection was {int(time_since_last_connection / 60) or 'N/A'} minutes ago"
            )
            credentials.connection_status = choices.OFFLINE
        except Exception:
            logger.exception(f"Unable to connect to {credentials} ({credentials.url})")
            credentials.connection_status = choices.OFFLINE
        credentials.save(update_fields=["last_connection", "connection_status"])
        return
    stale_credentials = Credentials.objects.filter(
        last_connection__lte=datetime.now(pytz.utc)
        - timedelta(seconds=settings.STILL_ALIVE_FREQUENCY - 3),
        valid=True,
    )
    # logger.info(f"Checking {stale_credentials.count()} parties for alive")
    c: Credentials
    for c in stale_credentials:
        if c.is_complete() and c.connection_status in {
            choices.CONNECTED,
            choices.OFFLINE,
        }:
            # since_last_time = (datetime.now(pytz.utc) - c.last_connection).seconds
            # logger.info(f"Checking that {c} is alive and well, last successful "
            #              f"connection was {int(since_last_time / 60)} min ago")
            check_still_alive.apply_async(
                (c.pk,), countdown=random.randint(0, stale_credentials.count())
            )


#  TODO This needs refactor will take care of it as soon as settings is up


def send_simulated_cpo_response(session, response_url):
    # # Abuse the OCPI headers to get access to the CPO instance
    # credentials = Credentials.objects.first()
    # token = credentials.theirs_base64()
    # headers = make_headers(token_base64=token, to=credentials.get_party_for_role(OcpiRolesEnum.CPO))
    # print(f'{headers=}')

    # Make sure we (the Celery process) have access to our corresponding CPO web process
    username = "simulator"
    password = "simulator"
    from django.contrib.auth.models import User

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        print(f"Creating user {username}...")
        user = User.objects.create_superuser(username=username)
    user.set_password(password)
    user.save()

    data = dict(result="ACCEPTED")
    print("Sending response to ", response_url)

    # Validate URL
    result = urlparse(response_url)
    assert all(
        [result.scheme, result.netloc]
    ), f"response_url is not in the correct format: {response_url}"

    response = requests.post(
        url=response_url, json=data, timeout=5, auth=HTTPBasicAuth(username, password)
    )
    print(
        "*** Response from CPO to simulator",
        response.status_code,
        response.text,
        session.evse,
    )


@app.task(max_retries=1, default_retry_delay=5)
def simulate_meter_values(
    session_pk,
    token_uid,
    connector_id,
    billed_to,
    evse_uid,
    response_url="",
    run_number=1,
):
    from ocpi22.models.session import Session

    session = Session.objects.get(pk=session_pk)

    if session.status == Session.COMPLETED:
        print("Session is not active, stopping simulation")
        return

    if session.status == Session.PENDING:
        print("Starting session")
        session.start_date_time = datetime.now(pytz.utc)
        # Don't actually start the session yet, it will be started in simulate_meter_values after a delay
        session.status = Session.ACTIVE
        session.save(update_fields=["status", "start_date_time"])
        session.send_updates()
        send_simulated_cpo_response(session, response_url)
    else:
        kwh = run_number * 0.21
        print(
            f"Simulating meter value {kwh} kWh for session {session_pk} with token {token_uid} "
            f"on connector {connector_id} #{run_number}."
        )

        session.stop_kwh = kwh
        session.update_last_updated()

        # session.update_charging_periods(kwh - session.start_kwh, soc, power, timestamp)

        session.calculate_price()
        session.save(
            update_fields=[
                "stop_kwh",
                "total_cost_incl_vat",
                "total_cost_excl_vat",
                "last_updated",
            ]
        )

        # The Session hashing doesn't seem to work for Celery worker tasks,
        # so let's make sure the update uses the most recent information
        session.serialize.cache_clear()

        # session_charging_periods = [cp for cp in session.chargingperiods.order_by('start_date_time')]
        # session.send_updates(session_charging_periods)
        # if run_number == 1:
        #     session.send_updates()
        # else:
        data = dict(kwh=kwh, last_updated=session.last_updated.isoformat())
        print(f"{data=}")
        session.send_updates(data, method="patch")

    # meter_values.process_meter_values(request=None, serializer=None, kwh=run_number, session=session)
    if run_number <= 100:
        simulate_meter_values.apply_async(
            (
                session_pk,
                token_uid,
                connector_id,
                billed_to,
                evse_uid,
                response_url,
                run_number + 1,
            ),
            countdown=3,
        )
    else:
        # Ok, we've reached the end of the simulation
        session.status = session.COMPLETED
        session.save(update_fields=["status"])
        session.send_updates()

        print(
            f"*** Done simulating meter values for session {session_pk} with token {token_uid}."
        )
