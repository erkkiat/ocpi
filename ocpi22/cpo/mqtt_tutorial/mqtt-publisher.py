import paho.mqtt.client as mqtt
import time
import json

# Define the MQTT broker details
broker = "localhost"
port = 1883
client_id = f"test_publisher_client"

# Define a test session_id
session_id = "BE*SMP*S*ABCDEF1234567890"
kwh = 10

# Topic to publish to
topic = f"session/{session_id}/metervalues"


# Callback when the client connects to the broker
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("Connected successfully to the broker.")
    else:
        print(f"Failed to connect, return code {rc}")


# Create an MQTT client instance
client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

# Attach the on_connect callback
client.on_connect = on_connect

# Connect to the broker
client.connect(broker, port)

# Start the MQTT client loop in a separate thread
client.loop_start()

# Publish test data periodically (e.g., every 5 seconds)
try:
    while True:
        # Convert the test data to JSON format
        test_data = {"kwh": kwh, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")}
        payload = json.dumps(test_data)

        # Publish the payload to the topic
        result = client.publish(topic, payload)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            print(f"Published to {topic}: {payload}")
            kwh += 1
        else:
            print(f"Failed to publish message: {result.rc}")

        time.sleep(2)
except KeyboardInterrupt:
    print("Publishing stopped.")

# Stop the MQTT client loop
client.loop_stop()
client.disconnect()
