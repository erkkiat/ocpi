import logging
import os
import sys
import uuid

import django
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

from ocpiconnector.settings.base import env_bool


def _load_envs():
    current_directory = os.getcwd()
    env_path = os.path.join(current_directory, ".env")
    load_dotenv(env_path)


def setup_django():
    _load_envs()
    sys.path.append(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
    )

    # Set the Django settings module
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ocpiconnector.settings.dev")
    django.setup()


setup_django()

from ocpi22.cpo.mqtt.services import (  # noqa
    process_meter_values_data,  # noqa
    process_status_update_data,  # noqa
)  # noqa

logger = logging.getLogger(__name__)


def get_topic(topic_env_var):
    topic = os.getenv(topic_env_var)
    if not topic:
        raise ValueError(f"{topic_env_var} is not set in the environment variables")
    return topic


def on_message(client, userdata, message):
    if "metervalues" in message.topic:
        logger.info("Received meter value message")
        process_meter_values_data(message)
        logger.info(
            f"Processed meter value message {message.payload} on topic {message.topic}"
        )
    if "status" in message.topic:
        logger.info("Received status update message")
        process_status_update_data(message)
        logger.info(
            f"Processed status update message {message.payload} on topic {message.topic}"
        )
    else:
        logger.error(f"Unknown topic {message.topic}")
        return


def on_connect(client, userdata, flags, rc, properties=None):
    meter_topic = get_topic("SMAPPEE_METER_VALUES_TOPIC")
    status_topic = get_topic("SMAPPEE_STATUS_UPDATE_TOPIC")
    print("Did I come here")
    if rc == 0:
        logger.info("Connected successfully to the broker.")
        client.subscribe(meter_topic)
        client.subscribe(status_topic)
        logger.info(f"Subscribed to [{meter_topic}] and [{status_topic}]")
    else:
        logger.error(f"Failed to connect, return code {rc}")


def get_broker_username_password():
    username = os.getenv("MQTT_USERNAME")
    password = os.getenv("MQTT_PASSWORD")
    if not username or not password:
        raise ValueError(
            "MQTT username or password is missing please check the environment variables, MQTT_USERNAME and MQTT_PASSWORD"
        )
    return username, password


def get_broker_and_port():
    broker = os.getenv("MQTT_BROKER")
    port = int(os.getenv("MQTT_PORT"))
    if not broker or not port:
        raise ValueError(
            "MQTTT Broker or port are missing please check the environment variables, MQTT_BROKER and MQTT_PORT"
        )
    return broker, port


def configure_client(client_id):
    username, password = get_broker_username_password()
    client = mqtt.Client(
        client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2
    )
    client.username_pw_set(username, password)
    client.on_connect = on_connect
    client.on_message = on_message
    return client


# if __name__ == "__main__": #TODO enable this for docker


def connect_client():
    client_id = f"ROAMING_{uuid.uuid4()}"
    client = configure_client(client_id)
    broker_url, port = get_broker_and_port()
    client.connect(broker_url, port)
    return client


def start_client(client):
    logger.info("Starting mqtt subscriber in the loop")
    if env_bool(os.getenv("MQTT_LOOP_FOREVER")):
        client.loop_forever()
    client.loop_start()


def stop_and_disconnect(client):
    client.loop_stop()
    client.disconnect()


mqtt_client = connect_client()
start_client(mqtt_client)
