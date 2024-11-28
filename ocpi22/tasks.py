import os
import random
from datetime import timedelta, datetime
from json import JSONDecodeError
from typing import Optional, Union
from unittest.mock import MagicMock
from urllib.parse import urlparse

import celery
import cronitor.celery
import pytz
import requests
import pprint

from celery import shared_task
from celery.schedules import crontab
from django.conf import settings
from django.http import HttpRequest
from django.utils.module_loading import import_string
from requests.auth import HTTPBasicAuth
from rest_framework import status
from sentry_sdk import capture_exception

from ocpi22 import choices
from ocpi22.ocpi.headers import make_headers
from ocpiconnector.party import Party
from util import unwrap

pp = pprint.PrettyPrinter(indent=4).pprint
zoined_token = os.environ.get("ZOINED_TOKEN")

# Set the default Django settings module for the 'celery' program.
if "DJANGO_SETTINGS_MODULE" not in os.environ:
    os.environ["DJANGO_SETTINGS_MODULE"] = "ocpiconnector.settings"

RESULT_EXPIRE_TIME = os.environ.get(
    "RESULT_EXPIRE_TIME", 1
)  # 1 second, we don't need the results of the tasks

app = celery.Celery("ocpi22.tasks", result_expires=RESULT_EXPIRE_TIME)

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")
# app.conf.task_default_queue = settings.CELERY_TASK_DEFAULT_QUEUE  # This is taken care of in production.py

pull_hour = random.randint(0, 3)
pull_minute = random.randint(0, 59)

# print(f'Pulling all objects daily at {pull_hour:02d}:{pull_minute:02d}')

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
}


@app.task
def celery_heartbeat() -> bool:
    return True


@shared_task(max_retries=3, retry_backoff=3600)
def pull_all_objects() -> bool:
    from ocpi22.models.credentials import Credentials
    from ocpi22.pull import schedule_full_update

    print("Starting a scheduled full OCPI object pull.")
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

    # Load task modules from all registered Django apps.
    app.autodiscover_tasks()

    CRONITOR_API_KEY = os.environ.get("CRONITOR_API_KEY")
    if CRONITOR_API_KEY:
        # Send pings automatically to Cronitor for Celery background tasks
        cronitor.celery.initialize(app, api_key=CRONITOR_API_KEY)
else:
    from ocpi22 import logging

    logging.error(f"{settings.HOSTNAME}: REDIS_URL not set, no connection to REDIS")


@shared_task
def send_ocpi_request(
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
) -> Optional[dict]:
    def write_to_file(text):
        with open("error-response.html", "w") as f:
            f.write(text)

    to = Party(to_country_code, to_party_id)
    sender = Party(from_country_code, from_party_id)
    from ocpi22 import logging

    try:
        headers = make_headers(token_base64, to=to, sender=sender)

        # Log the message to Sentry
        # sentry_sdk.set_context('data', data)

        if isinstance(data, dict):
            kwargs.update(dict(url=url, json=data, headers=headers))
        else:
            kwargs.update(dict(url=url, data=data, headers=headers))

        # Call the specified method in requests, for example, if method == 'put', call requests.put
        function = getattr(requests, method.lower())
        if not function:
            raise NotImplementedError(
                f"Method {method} is not supported for send_ocpi_request"
            )

        result: requests.Response = function(**kwargs)

        if result.status_code >= status.HTTP_400_BAD_REQUEST:
            logging.error(
                f"{settings.HOSTNAME}: Unable to send update to {url}: {result.status_code} - {result.reason}"
            )
            write_to_file(result.text)
        else:
            logging.info(
                f"Sending {method.upper()} {title} request to {url}, "
                f"response {result.status_code} (time {result.elapsed})"
            )

        # Todo: This needs to be done some other way than starting the Django logic
        #       We want to refresh the last connection time, but only if the request was successful
        # if credentials_id:
        #     from ocpi22.models.credentials import Credentials
        #
        #     credentials = Credentials.get_if_exists(pk=credentials_id)
        #     if credentials:
        #         credentials.update_last_connection()

        # # Log the response to Sentry
        # if hasattr(result, 'data') and result.data:
        #     sentry_sdk.set_context('result', result.json())

        try:
            result_json = result.json()
        except requests.exceptions.JSONDecodeError as e:
            write_to_file(result.text)
            logging.error(f"Unable to decode JSON response from {url}: {e}")
            result_json = dict()
        return dict(
            status_code=result.status_code,
            json=result_json,
            headers=dict(result.headers) if result.headers else {},
            sender=dict(country_code=to_country_code, party_id=to_party_id),
        )
    except (IOError, JSONDecodeError) as e:
        logging.error(
            f"{settings.HOSTNAME}: Unable to send an OCPI request to {str(to)} at {url}: {e}"
        )

        # Todo: This also needs to be done some other way than starting the Django logic
        # from ocpi22.models.credentials import Credentials
        #
        # if credentials_id:
        #     Credentials.objects.filter(
        #         pk=credentials_id, connection_status=choices.CONNECTED
        #     ).update(connection_status=choices.OFFLINE)
        capture_exception(e)
        return None


@shared_task(max_retries=2, retry_backoff=2)
def exchange_credentials(token, url):
    from ocpiconnector.management.commands import exchange_credentials

    command = exchange_credentials.Command()
    command.handle(token_a=token, versions_endpoint_url=url)


@shared_task(max_retries=2, retry_jitter=True, retry_backoff=120)
def pull_objects(
    object_list, limit=10, delay=2, total_objects=0, credentials_id=None, **kwargs
) -> None:
    from ocpi22 import logging
    from ocpi22.models.credentials import Credentials

    assert isinstance(
        credentials_id, int
    ), f"credentials_id is missing: {credentials_id}"
    credentials = Credentials.objects.get(pk=credentials_id)

    try:
        if not object_list:
            logging.info("Empty object list, nothing to pull")
            return
        next_url = ""
        obj = object_list[0]
        url = kwargs.pop("url", obj.get("url", ""))
        if url:
            if "limit=" not in url:
                url = f"{url}?limit={limit}"
            response = send_ocpi_request(data=dict(), url=url, **kwargs)
            if response and response.get("status_code") < status.HTTP_400_BAD_REQUEST:
                next_url, _rel = (
                    response.get("headers").get("Link", ";").strip("<>").split(";")
                )
                model = obj.get("model")
                viewset = import_string(obj.get("viewset"))
                items = response.get("json", {}).get("data", [])
                total_objects += len(items)
                for i in items:
                    try:
                        # TODO: Check that party matches with Credentials, don't allow third party data
                        request = HttpRequest()
                        request.party_specified_in_url = True
                        party = Party(i.get("country_code"), i.get("party_id"))
                        if not party:
                            logging.error(
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
                                logging.error(
                                    f"Party {party} in the pulled data doesn't match party "
                                    f"{credentialsrole.party_str()} in the credentialsrole. "
                                    "The other party may be spoofing a location of another operator."
                                )
                                continue

                        # Check if we have pulled our own object
                        from ocpi22.util import is_our_identifier

                        if is_our_identifier(credentialsrole.party):
                            logging.info(
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
                    except Exception as e:
                        logging.error(
                            f"Unable to update {model} using data pulled from url {url} "
                            f"for uid {i.get('uid', i.get('id', ''))}: {e}."
                        )
                        raise
                if next_url:
                    kwargs["url"] = next_url

        if not next_url:
            object_list.pop(0)
            if not len(object_list):
                logging.info(f"Total of {total_objects} objects pulled")
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
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        logging.error(f"Unable to pull objects: {e}")


@shared_task(max_retries=0)  # We will do this every 5 minutes anyways
def check_still_alive(credentials_id: int = None) -> None:
    from ocpi22.models.credentials import Credentials
    from ocpi22 import logging

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
            logging.info(f"{credentials} is alive")
        except IOError as e:
            logging.error(
                f"{settings.HOSTNAME}: {credentials} is *NOT* alive ({credentials.url}), "
                f"last connection was {int(time_since_last_connection / 60) or 'N/A'} minutes ago: {e}"
            )
            credentials.connection_status = choices.OFFLINE
        except Exception as e:
            logging.error(
                f"{settings.HOSTNAME}: STILL ALIVE CHECK: Unable to connect to "
                f"{credentials} ({credentials.url}): {type(e)} - {e}"
            )
            credentials.connection_status = choices.OFFLINE
        credentials.save(update_fields=["last_connection", "connection_status"])
        return
    stale_credentials = Credentials.objects.filter(
        last_connection__lte=datetime.now(pytz.utc)
        - timedelta(seconds=settings.STILL_ALIVE_FREQUENCY - 3),
        valid=True,
    )
    # logging.info(f"Checking {stale_credentials.count()} parties for alive")
    c: Credentials
    for c in stale_credentials:
        if c.is_complete() and c.connection_status in {
            choices.CONNECTED,
            choices.OFFLINE,
        }:
            # since_last_time = (datetime.now(pytz.utc) - c.last_connection).seconds
            # logging.info(f"Checking that {c} is alive and well, last successful "
            #              f"connection was {int(since_last_time / 60)} min ago")
            check_still_alive.apply_async(
                (c.pk,), countdown=random.randint(0, stale_credentials.count())
            )


@app.task(max_retries=5, default_retry_delay=120)
def send_data_to_analytics(data: Union[dict, list], url):
    from ocpi22 import logging

    if not zoined_token:
        # logging.info(f'No Zoined token set => no update to analytics')
        return
    headers = {
        "content-type": "application/json",
        "Authorization": f"Bearer {zoined_token}",
    }
    # Todo: Async send
    if isinstance(data, dict):
        data = [data]
    response = requests.post(url=url, json=data, headers=headers, timeout=5)
    if response.status_code != 200:
        logging.error(f"Unable to send update to analytics: {response.text}")
    # else:
    #     logging.info(f'Update sent to analytics: {response.text}')


#  TODO This needs refactor will take care of it as soon as settings is up
if settings.SEND_DATA_TO_ANALYTICS:
    send_data_to_analytics = MagicMock()


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
