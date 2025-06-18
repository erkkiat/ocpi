import os
from logging import getLogger

from pydantic import ValidationError

from ocpi22.cpo.mqtt.mqtt_client import MQTTClientSingleton
from ocpi22.cpo.mqtt.schemas import TokenAuthorizationResponse

logger = getLogger(__name__)


def _get_auth_topic_name(topi_env_ar: str):
    topic = os.getenv(topi_env_ar)
    if topic and "$share" in topic:
        return "/".join(topic.split("/")[2:])
    else:
        return "servicelocation/roaming/authresponse"


def publish_auth_response(payload: TokenAuthorizationResponse):
    topic = _get_auth_topic_name("SMAPPEE_AUTH_RESPONSE")
    client = MQTTClientSingleton().get_client()
    try:
        body = payload.model_dump_json(exclude_unset=True)
    except ValidationError:
        logger.exception("Failed serializing MQTT auth payload")
        return

    try:
        info = client.publish(topic, body)
        if info.rc != 0:
            logger.error("MQTT publish failed with result code %s", info.rc)
    except Exception:
        logger.exception("Failed to publish auth response to MQTT")
