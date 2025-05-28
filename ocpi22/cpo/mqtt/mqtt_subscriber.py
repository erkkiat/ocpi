import os
import ssl
import sys
import time
import uuid
import threading
from logging import getLogger
from typing import Optional

import django
import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from distutils.util import strtobool

logger = getLogger(__name__)


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


# Get topics after Django setup
meter_topic = get_topic("SMAPPEE_METER_VALUES_TOPIC")
status_topic = get_topic("SMAPPEE_STATUS_UPDATE_TOPIC")


def on_message(client, userdata, message):
    if meter_topic.split("/")[-1] in message.topic:
        logger.info("Received meter value message")
        process_meter_values_data(message)
        logger.info(
            f"Processed meter value message {message.payload} on topic {message.topic}"
        )
    elif status_topic.split("/")[-1] in message.topic:
        logger.info("Received status update message")
        process_status_update_data(message)
        logger.info(
            f"Processed status update message {message.payload} on topic {message.topic}"
        )
    else:
        logger.error(f"Unknown topic {message.topic}")
        return


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logger.info("Connected successfully to the broker.")
        _subscribe(client, meter_topic)
        _subscribe(client, status_topic)
        logger.info(f"Subscribed to [{meter_topic}] and [{status_topic}]")
    else:
        logger.error(f"Failed to connect, return code {rc}")


class MQTTClientSingleton:
    _instance: Optional["MQTTClientSingleton"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "MQTTClientSingleton":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.client: Optional[mqtt.Client] = None
        self._initialized = True
        logger.info("MQTT Client Singleton initialized")

    def get_client(self):
        if self.client is None:
            self.client = self._create_and_connect_client()
        return self.client

    def _create_and_connect_client(self):
        client_id = f"ROAMING_{uuid.uuid4()}"
        client = self._configure_client(client_id)
        self._connect_client(client)
        return client

    def _configure_client(self, client_id):
        username, password = get_broker_username_password()
        client = mqtt.Client(
            client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )
        client.username_pw_set(username, password)
        if strtobool(os.getenv("MQTT_USE_SSL", "False")):
            client = self._configure_ssl(client)
        client.on_connect = on_connect
        client.on_message = on_message
        return client

    def _configure_ssl(self, client) -> mqtt.Client:
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)
        return client

    def _connect_client(self, client, retries=5, delay=5):
        broker_url, port = get_broker_and_port()

        for attempt in range(retries):
            try:
                logger.info(
                    f"Attempting to connect to MQTT broker {broker_url}:{port} (attempt {attempt + 1}/{retries})..."
                )
                client.connect(broker_url, port)
                logger.info(
                    f"Connected successfully to the MQTT broker {broker_url}:{port}"
                )
                return
            except Exception as e:
                logger.error(f"Connection attempt {attempt + 1} failed: {e}")
                if attempt < retries - 1:
                    logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    logger.error("Max retries reached. Giving up.")
                    raise ConnectionError(
                        "Failed to connect to MQTT broker after retries."
                    ) from e

    def reset_client(self):
        with self._lock:
            if self.client:
                self.client.loop_stop()
                self.client.disconnect()
                self.client = None


# Legacy functions for backward compatibility
def configure_client(client_id):
    """Legacy function - now uses singleton"""
    return MQTTClientSingleton().get_client()


def connect_client(retries=5, delay=5):
    """Legacy function - now uses singleton"""
    return MQTTClientSingleton().get_client()


def get_mqtt_client():
    return MQTTClientSingleton().get_client()


def start_client(client, loop_forever=True):
    if loop_forever:
        logger.info("Starting mqtt subscriber in the loop")
        client.loop_forever()
    else:
        client.loop_start()


def stop_and_disconnect(client):
    MQTTClientSingleton().reset_client()


if __name__ == "__main__":
    logger = getLogger(__name__)
    from ocpiconnector.settings.base import env_bool  # noqa

    loop_forever = env_bool("MQTT_LOOP_FOREVER", True)
    mqtt_singleton = MQTTClientSingleton()
    mqtt_client = mqtt_singleton.get_client()
    start_client(mqtt_client, loop_forever)
