"""
This is a test client for publishing messages to an MQTT broker.
- Assuming a MQTT broker on localhost
- Set the messages_per_second to control the rate of publishing (the number is approximate)
"""
import os
import uuid
from datetime import datetime

import orjson
import paho.mqtt.client as mqtt
import time

import pytz
from dotenv import load_dotenv


def _load_envs():
    base_dir = os.getcwd()
    env_path = os.path.join(base_dir, "../../../.env")
    load_dotenv(env_path)


_load_envs()

from ocpi22.cpo.mqtt.schemas import CachedSession
from ocpi22.routing import Route
from ocpiconnector.party import Party
from util import RedisStore, OCPIVersion



# Define the MQTT broker details
broker = "localhost"
port = 1883
client_id = f"test_publisher_client_{uuid.uuid4()}"

session_id = "FI*CPO*S*AADDFDAA1AB24BE885305FB396E"
kwh = 0.5

topic = f"session/{session_id}/metervalues"
messages_per_second = 10

# Simulate a start_session which sets up the session cache for the corresponding session
token_store = RedisStore(namespace="sessioncache")

route = Route(to=Party("BE", "SMP"), identifier='sessions', token_base64="1234567890",
              url="http://localhost:8002/ocpi/cpo/2.2/sessions/1234567890",
              credentials_id=1, alive=True, direct=True, version=OCPIVersion("221"))
cs = CachedSession(session_id=session_id,
                     kwh=10, timestamp=datetime.now(pytz.utc),
                     route_to_msp=route)
if not token_store.retrieve(session_id):
    token_store.store(session_id, cs)


# Callback when the client connects to the broker
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("Connected successfully to the broker.")
    else:
        print(f"Failed to connect, return code {rc}")


client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.connect(broker, port)
client.loop_start()

try:
    while True:
        # Convert the test data to JSON format
        test_data = {"session_id": session_id, "kwh": kwh, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")}
        payload = orjson.dumps(test_data)

        # Publish the payload to the topic
        result = client.publish(topic, payload)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            print(f"Published to {topic}: {payload}")
            kwh += 1
        else:
            print(f"Failed to publish message: {result.rc}")

        time.sleep(1/messages_per_second)
except KeyboardInterrupt:
    print("Publishing stopped.")

# Stop the MQTT client loop
client.loop_stop()
client.disconnect()
