import os
import ssl
import threading
import time
import uuid
from distutils.util import strtobool
from functools import wraps
from logging import getLogger
from typing import Optional, Callable

from paho.mqtt import client as mqtt
from django.db import close_old_connections

from ocpiconnector.db_services import ensure_db_connection
from ocpi22.cpo.mqtt import mqtt_handler

logger = getLogger(__name__)


class MQTTClientSingleton:
    """
    Thread-safe singleton MQTT client with automatic DB connection management.

    Features:
    1. Reuses client_id across reconnections (memory optimization)
    2. Automatically wraps ALL callbacks with:
       - DB connection lifecycle management (close before/after)
       - DB error recovery with retry (via ensure_db_connection)
       - Exception resilience (don't crash subscriber)
    3. Proper cleanup on reset

    Usage:
        mqtt_singleton = MQTTClientSingleton()
        mqtt_singleton.start_client(loop_forever=True)
    """

    _instance: Optional["MQTTClientSingleton"] = None
    _lock = threading.Lock()
    _client_id: Optional[str] = None  # ✅ Class variable - shared across reconnections

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

        if not MQTTClientSingleton._client_id:
            MQTTClientSingleton._client_id = f"ROAMING_{uuid.uuid4()}"

        logger.info(f"MQTT Client Singleton initialized with ID: {self._client_id}")

    def _wrap_db_safe_callback(self, callback: Callable):
        """
        Wrap MQTT callback with comprehensive protection:

        1. DB connection lifecycle management:
           - close_old_connections() before callback
           - close_old_connections() after callback (always)

        2. DB error recovery (via @ensure_db_connection):
           - Catches connection errors
           - Retries once after reconnecting

        3. Exception resilience:
           - Catches all exceptions
           - Logs errors
           - Doesn't crash MQTT subscriber

        This ensures ALL MQTT callbacks are:
        - Protected from DB connection leaks
        - Resilient to DB connection errors
        - Safe from crashing the subscriber
        """

        @ensure_db_connection
        @wraps(callback)
        def safe_callback(client, userdata, *args, **kwargs):
            try:
                return callback(client, userdata, *args, **kwargs)
            except Exception as e:
                logger.error(
                    f"Error in MQTT callback {callback.__name__}: {type(e).__name__}",
                    exc_info=True,
                )
            finally:
                close_old_connections()

        return safe_callback

    def get_client(self):
        if self.client is None:
            self.client = self._create_and_connect_client()
        return self.client

    def _create_and_connect_client(self):
        client = self._configure_client(self._client_id)
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

        client.on_connect = self._wrap_db_safe_callback(mqtt_handler.on_connect)
        client.on_message = self._wrap_db_safe_callback(mqtt_handler.on_message)

        if hasattr(mqtt_handler, "on_disconnect"):
            client.on_disconnect = self._wrap_db_safe_callback(
                mqtt_handler.on_disconnect
            )

        logger.info("MQTT callbacks wrapped with automatic DB connection management")

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
                    f"Connecting to MQTT broker {broker_url}:{port} "
                    f"(attempt {attempt + 1}/{retries})"
                )
                client.connect(broker_url, port, keepalive=60)
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
                try:
                    self.client.loop_stop()
                    self.client.disconnect()

                    self.client.on_connect = None
                    self.client.on_message = None
                    self.client.on_disconnect = None

                    self.client = None
                    logger.info("MQTT client stopped and disconnected")
                except Exception as e:
                    logger.exception(f"Error during client reset: {e}")

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
