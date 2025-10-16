import os
from distutils.util import strtobool
from logging import getLogger

from paho.mqtt.client import MQTT_ERR_SUCCESS

from ocpi22.cpo.mqtt.services import (
    process_meter_values_data,
    process_status_update_data,
    process_authorize_data,
)

logger = getLogger(__name__)


def get_topic(topic_env_var):
    topic = os.getenv(topic_env_var)
    if not topic:
        raise ValueError(f"{topic_env_var} is not set in the environment variables")
    return topic


METER_TOPIC = get_topic("SMAPPEE_METER_VALUES_TOPIC")
STATUS_TOPIC = get_topic("SMAPPEE_STATUS_UPDATE_TOPIC")
AUTH_REQUEST_TOPIC = get_topic("SMAPPEE_AUTH_REQUEST_TOPIC")


def _subscribe(client, topic):
    result, mid = client.subscribe(topic)
    if result != MQTT_ERR_SUCCESS:
        logger.error(f"Failed to subscribe to {topic} with error code {result}")
    else:
        logger.info(f"Successfully subscribed to {topic}")


def on_message(client, userdata, message):
    topic = message.topic
    payload_size = len(message.payload) if message.payload else 0

    try:
        if METER_TOPIC.split("/")[-1] in topic:
            logger.info(
                f"Received meter value message on {topic} ({payload_size} bytes)"
            )
            process_meter_values_data(message)
            logger.info(f"Processed meter value message on {topic}")
        elif STATUS_TOPIC.split("/")[-1] in topic:
            logger.info(
                f"Received status update message on {topic} ({payload_size} bytes)"
            )
            process_status_update_data(message)
            logger.info(f"Processed status update message on {topic}")
        elif AUTH_REQUEST_TOPIC.split("/")[-1] in topic:
            enable_mqtt_authorize = strtobool(
                os.getenv("ENABLE_MQTT_AUTHORIZE", "False")
            )
            if not enable_mqtt_authorize:
                logger.warning(
                    f"Authorizing over mqtt is not enabled for {os.getenv('ENV')}, please use http authorize instead"
                )
                return
            logger.info(f"Received authorize message on {topic} ({payload_size} bytes)")
            process_authorize_data(message)
            logger.info(f"Processed auth message on {topic}")
        else:
            logger.error(f"Unknown topic {topic}")
            return
    except Exception:
        logger.error(
            f"MQTT message processing failed on topic {topic} - subscriber continues running",
            exc_info=True,
        )
        return


def on_connect(client, userdata, flags, rc, properties=None):
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
