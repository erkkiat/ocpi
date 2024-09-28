import uuid

import paho.mqtt.client as mqtt

# Define the MQTT broker details
broker = "localhost"
port = 1883
client_id = f"ocpiconnector_{uuid.uuid4()}"

# Shared subscription topic with wildcard to capture all session_ids
topic = "$share/session_group/session/+/metervalues"


def on_message(client, userdata, msg):
    # Callback when the client receives a message
    print(f"Received message on topic {msg.topic}: {msg.payload.decode()}")


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
