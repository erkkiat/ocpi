"""
This is a test client for publishing messages to an MQTT broker.
- Assuming a MQTT broker on localhost
- Set the messages_per_second to control the rate of publishing (the number is approximate)
"""
import uuid

import orjson
import paho.mqtt.client as mqtt
import time

# Define the MQTT broker details
broker = "localhost"
port = 1883
client_id = f"test_publisher_client_{uuid.uuid4()}"

session_id = "BE*SMP*S*ABCDEF1234567890"
kwh = 10

topic = f"session/{session_id}/metervalues"
messages_per_second = 1000


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
