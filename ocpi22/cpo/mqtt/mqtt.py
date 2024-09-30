import os
import uuid

import paho.mqtt.client as mqtt
from django.conf import settings
from dotenv import load_dotenv
from pydantic import ValidationError


def _load_envs():
    base_dir = os.getcwd()
    env_path = os.path.join(base_dir, "../../../.env")
    load_dotenv(env_path)


_load_envs()

from schemas import MeterValues

broker = settings.MQTT_BROKER
port = settings.MQTT_PORT

# Todo: should this be a process ID or something? Cannot overlap between processes
client_id = f"ocpiconnector_{uuid.uuid4()}"

# Shared subscription topic with wildcard to capture all session_ids
topic = "$share/session_group/session/+/metervalues"


def on_message(client, userdata, msg):
    from ocpi22.cpo.mqtt.tasks import process_meter_values

    # Callback when the client receives a message
    # print(f"Received message on topic {msg.topic}: {msg.payload.decode()}")
    try:
        meter_values = MeterValues.parse_raw(msg.payload.decode())
        process_meter_values(**meter_values.model_dump())
    except ValidationError as e:
        print(f"Failed to parse message: {e}")


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
