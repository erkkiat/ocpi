import os
from distutils.util import strtobool
from logging import getLogger

from paho.mqtt.client import MQTT_ERR_SUCCESS

from ocpi22.cpo.mqtt.services import (  # noqa
    process_meter_values_data,  # noqa
    process_status_update_data,  # noqa
    process_authorize_data,  # noqa
)  # noqa

logger = getLogger(__name__)


def _subscribe(client, topic):
    result, mid = client.subscribe(topic)
    if result != MQTT_ERR_SUCCESS:
        logger.error(f"Failed to subscribe to {topic} with error code {result}")
    else:
        logger.info(f"Successfully subscribed to {topic}")


def get_topic(topic_env_var):
    topic = os.getenv(topic_env_var)
    if not topic:
        raise ValueError(f"{topic_env_var} is not set in the environment variables")
    return topic


def on_message(client, userdata, message):
    METER_TOPIC = get_topic("SMAPPEE_METER_VALUES_TOPIC")
    STATUS_TOPIC = get_topic("SMAPPEE_STATUS_UPDATE_TOPIC")
    AUTH_REQUEST_TOPIC = get_topic("SMAPPEE_AUTH_REQUEST_TOPIC")
    try:
        if METER_TOPIC.split("/")[-1] in message.topic:
            logger.info("Received meter value message")
            process_meter_values_data(message)
            logger.info(
                f"Processed meter value message {message.payload} on topic {message.topic}"
            )
        elif STATUS_TOPIC.split("/")[-1] in message.topic:
            logger.info("Received status update message")
            process_status_update_data(message)
            logger.info(
                f"Processed status update message {message.payload} on topic {message.topic}"
            )
        elif AUTH_REQUEST_TOPIC.split("/")[-1] in message.topic:
            enable_mqtt_authorize = strtobool(
                os.getenv("ENABLE_MQTT_AUTHORIZE", "False")
            )
            if not enable_mqtt_authorize:
                logger.warning(
                    f"Authorizing over mqtt is not enabled for {os.getenv('ENV')}, please use http authorize instead"
                )
                return
            logger.info("Received authorize message")
            process_authorize_data(message)
            logger.info(
                f"Processed auth message {message.payload} on topic {message.topic}"
            )
        else:
            logger.error(f"Unknown topic {message.topic}")
            return
    except Exception:
        logger.error(
            "MQTT message processing failed - subscriber continues running",
            extra={"mqtt_message": message},
            exc_info=True,
        )
        return


def on_connect(client, userdata, flags, rc, properties=None):
    METER_TOPIC = get_topic("SMAPPEE_METER_VALUES_TOPIC")
    STATUS_TOPIC = get_topic("SMAPPEE_STATUS_UPDATE_TOPIC")
    AUTH_REQUEST_TOPIC = get_topic("SMAPPEE_AUTH_REQUEST_TOPIC")
    if rc == 0:
        logger.info("Connected successfully to the broker.")
        _subscribe(client, METER_TOPIC)
        _subscribe(client, STATUS_TOPIC)
        _subscribe(client, AUTH_REQUEST_TOPIC)
        logger.info(
            f"Subscribed to [{METER_TOPIC}], [{STATUS_TOPIC}], and [{AUTH_REQUEST_TOPIC}]"
        )
    else:
        logger.error(f"Failed to connect, return code {rc}")
