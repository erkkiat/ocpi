import os
import sys
import uuid
from logging import getLogger

import django
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

logger = getLogger("__name__")


def _load_envs():
    environment = os.getenv("ENV")
    if environment in ["test", "development"]:
        current_directory = os.getcwd()
        env_path = os.path.join(current_directory, "test.env")
        load_dotenv(env_path)
        logger.info("Loaded test.env from root")
    else:
        logger.info("Skipping dotenv for production and staging")

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

def _subscribe(client, topic):
    result, mid = client.subscribe(topic)
    if result != mqtt.MQTT_ERR_SUCCESS:
        logger.error(f"Failed to subscribe to {topic} with error code {result}")
    else:
        logger.info(f"Successfully subscribed to {topic}")


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
    elif "status" in message.topic:
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
    if rc == 0:
        logger.info("Connected successfully to the broker.")
        _subscribe(client, meter_topic)
        _subscribe(client, status_topic)
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
    port = os.getenv("MQTT_PORT")
    if not broker or not port:
        raise ValueError(
            "MQTTT Broker or port are missing please check the environment variables, MQTT_BROKER and MQTT_PORT"
        )
    return broker, int(port)


def configure_client(client_id):
    username, password = get_broker_username_password()
    client = mqtt.Client(
        client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2
    )
    client.username_pw_set(username, password)
    client.on_connect = on_connect
    client.on_message = on_message
    return client


def connect_client():
    client_id = f"ROAMING_{uuid.uuid4()}"
    client = configure_client(client_id)
    broker_url, port = get_broker_and_port()
    client.connect(broker_url, port)
    return client


def start_client(client, loop_forever=True):
    if loop_forever:
        logger.info("Starting mqtt subscriber in the loop")
        client.loop_forever()
    else:
        client.loop_start()


def stop_and_disconnect(client):
    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    from ocpiconnector.settings.base import env_bool  # noqa
    loop_forever = env_bool("MQTT_LOOP_FOREVER")
    mqtt_client = connect_client()
    start_client(mqtt_client, loop_forever)
