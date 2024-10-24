import logging
import os
import re
import uuid

import paho.mqtt.client as mqtt
from django.conf import settings
from dotenv import load_dotenv
from pydantic import ValidationError
from rest_framework.generics import get_object_or_404

from ocpi22.cpo.mqtt.tasks import process_meter_values
from ocpi22.models.location import Evse


def _load_envs():
    base_dir = os.getcwd()
    env_path = os.path.join(base_dir, "../../../.env")
    load_dotenv(env_path)


_load_envs()

from schemas import MeterValues, EvseStatusUpdate

logger = logging.getLogger(__name__)

broker = settings.MQTT_BROKER
port = settings.MQTT_PORT

# Todo: should this be a process ID or something? Cannot overlap between processes
client_id = f"ocpiconnector_{uuid.uuid4()}"

METER_TOPIC_PATTERN = r"\$share/session_group/session/([^\/]+)/meter"
STATUS_TOPIC_PATTERN = r"\$share/session_group/session/([^\/]+)/status"

# Shared subscription topic with wildcard to capture all session_ids
topic = "$share/session_group/session/+/metervalues"
status = "$share/session_group/session/+/statusupdates"


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


def _process_status_update(message) -> None:
    decoded_evse_message = _decode_message(message)
    if not decoded_evse_message:
        return
    try:
        evse_schema = EvseStatusUpdate.model_validate_json(decoded_evse_message)
    except ValidationError:
        logger.exception(f"Failed to parse {message.topic} message")
        return
    evse = get_object_or_404(Evse, evse_uuid=evse_schema.evse_uuid)
    evse.status = evse_schema.status
    evse.save(update_fields=["status", "last_updated"])
    evse.send_status_updates()
    return


def on_message(client, userdata, message):
    if re.match(METER_TOPIC_PATTERN, message.topic):
        _process_meter_values(message)
    elif re.match(STATUS_TOPIC_PATTERN, message.topic):
        _process_status_update(message)
    else:
        logger.error(f"Unknown topic {message.topic}")
        return


#     from ocpi22.cpo.mqtt.tasks import process_meter_values
#
#     # Callback when the client receives a message
#     # print(f"Received message on topic {message.topic}: {message.payload.decode()}")
#     try:
#         meter_values = MeterValues.model_validate_json(message.payload.decode())
#         process_meter_values(**meter_values.model_dump())  # Switch to the below call after setting up celery
#         # process_meter_values.apply_async(kwargs=meter_values.model_dump(), expires=35)
#     except ValidationError as e:
#         print(f"Failed to parse message: {e}")


def on_connect(client, userdata, flags, rc, properties=None):
    # Callback when the client connects to the broker
    if rc == 0:
        print("Connected successfully to the broker.")
        client.subscribe(topic)
        print(f"Subscribed to topic: {topic}")
    else:
        print(f"Failed to connect, return code {rc}")


# Create an MQTT client instance
client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

# Attach the on_connect and on_message callbacks
client.on_connect = on_connect
client.on_message = on_message

# Connect to the broker
client.connect(broker, port)

# Start the MQTT client loop to listen for messages
client.loop_forever()
