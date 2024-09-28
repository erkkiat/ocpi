# MQTT Example

This simple example demonstrates how to use the MQTT protocol 
to receive meter values from a charging station using a shared subscription.
The shared subscription works as a load balancing mechanism, where multiple
subscribers can receive messages from the same topic while making sure that
only one subscriber will process the message.

## Usage

- Start the `emqx` MQTT broker using `docker-compose`
- Start the subscriber `mqtt.py` on the command line or using pycharm
- Start the publisher `mqtt_publisher.py` on the command line or using pycharm

You should see output similar to this when running two subscribers in parallel:

```
Connected successfully to the broker.
Subscribed to topic: $share/session_group/session/+/metervalues
Received message on topic session/12345/metervalues: {"meterValue": 11, "timestamp": "2024-09-28T09:30:38Z"}
Received message on topic session/12345/metervalues: {"meterValue": 13, "timestamp": "2024-09-28T09:30:42Z"}
Received message on topic session/12345/metervalues: {"meterValue": 15, "timestamp": "2024-09-28T09:30:46Z"}
Received message on topic session/12345/metervalues: {"meterValue": 17, "timestamp": "2024-09-28T09:30:50Z"}
```
