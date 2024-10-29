import logging
import os
import re
import uuid
from datetime import datetime

import paho.mqtt.client as mqtt
from celery import shared_task
from django.conf import settings
from django.db.models import F, Value
from django.db.models.functions import Concat
from dotenv import load_dotenv
from pydantic import ValidationError
from rest_framework.generics import get_object_or_404

from integrations.hubject.schemas import EvseStatus
from ocpi22.cpo.mqtt.tasks import process_meter_values
from ocpi22.models.location import Evse, Location


def _load_envs():
    base_dir = os.getcwd()
    env_path = os.path.join(base_dir, "../../../.env")
    load_dotenv(env_path)


_load_envs()

from schemas import MeterValues, EvseStatusUpdate

logger = logging.getLogger(__name__)

broker = settings.MQTT_BROKER
port = settings.MQTT_PORT
METER_TOPIC = settings.SMAPPEE_METER_VALUES_TOPIC
STATUS_TOPIC = settings.SMAPPEE_STATUS_UPDATE_TOPIC

# Todo: should this be a process ID or something? Cannot overlap between processes
client_id = f"ocpiconnector_{uuid.uuid4()}"


def _decode_message(message):
    try:
        return message.payload.decode()
    except UnicodeDecodeError:
        logger.exception(f"Failed to decode {message.topic} message")
        return None


def _process_meter_values(message) -> None:
    decoded_meter_message = _decode_message(message)
    if not decoded_meter_message:
        return
    try:
        meter_values = MeterValues.model_validate_json(decoded_meter_message)
    except ValidationError:
        logger.exception(f"Failed to validate {message.opic} message")
        return
    try:
        process_meter_values.apply_async(**meter_values.model_dump(),
                                         expires=35)  # Switch to the below call after setting up celery
    except Exception as e:
        logger.exception(f"Failed to parse message: {e}")
    return


def get_evse_by_uid(uid: str):
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
def _save_and_send_status_updates(evse_uid: str, status: str, last_updated: datetime) -> None:
    evse = get_evse_by_uid(evse_uid)
    evse.status = status
    evse.save(update_fields=["status", "last_updated"])
    evse.send_status_updates()
    return


def _process_status_update(message) -> None:
    decoded_evse_message = _decode_message(message)
    if not decoded_evse_message:
        return
    try:
        evse_schema = EvseStatusUpdate.model_validate_json(decoded_evse_message)
    except ValidationError:
        logger.exception(f"Failed to parse {message.topic} message")
        return
    _save_and_send_status_updates.apply_async(**evse_schema.model_dump(),
                                              expires=35)  # Switch to the below call after setting up celery
    return


def on_message(client, userdata, message):
    if "session" in message.topic and "metervalues" in message.topic:
        _process_meter_values(message)
        logger.info(f"Received message {message.payload} on topic {message.topic}")
    elif "session" in message.topic and "statusupdates" in message.topic:
        _process_status_update(message)
        logger.info(f"Received message {message.payload} on topic {message.topic}")
    else:
        logger.error(f"Unknown topic {message.topic}")
        return


def on_connect(client, userdata, flags, rc, properties=None):
    # Callback when the client connects to the broker
    if rc == 0:
        logger.info("Connected successfully to the broker.")
        client.subscribe(METER_TOPIC)
        client.subscribe(STATUS_TOPIC)
        logger.info(f"Subscribed to [{METER_TOPIC}] and [{STATUS_TOPIC}]")
    else:
        logger.error(f"Failed to connect, return code {rc}")


# Create an MQTT client instance
client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

# Attach the on_connect and on_message callbacks
client.on_connect = on_connect
client.on_message = on_message

# Connect to the broker
client.connect(broker, port)

# Start the MQTT client loop to listen for messages
client.loop_forever()
