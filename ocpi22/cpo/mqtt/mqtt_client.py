import os
import ssl
import threading
import time
import uuid
from distutils.util import strtobool
from logging import getLogger
from typing import Optional

from paho.mqtt import client as mqtt

from ocpi22.cpo.mqtt.mqtt_handler import on_connect, on_message

logger = getLogger(__name__)


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

    def start_client(self, loop_forever=True):
        client = self.get_client()
        if loop_forever:
            logger.info("Starting mqtt subscriber in the loop")
            client.loop_forever()
        else:
            client.loop_start()

    def reset_client(self):
        with self._lock:
            if self.client:
                self.client.loop_stop()
                self.client.disconnect()
                self.client = None
                logger.info("MQTT client stopped and disconnected")

    def is_connected(self):
        return self.client is not None and self.client.is_connected()


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
