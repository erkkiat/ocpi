import os
from logging import getLogger

from pydantic import ValidationError

from ocpi22.cpo.mqtt.schemas import TokenAuthorizationResponse

logger = getLogger(__name__)


def _get_auth_topic_name(topic_env_var: str) -> str:
    topic = os.getenv(topic_env_var, "servicelocation/roaming/authresponse")
    if topic.startswith("$share/"):
        return topic.split("/", 2)[2]
    return topic


def publish_auth_response(payload: TokenAuthorizationResponse) -> None:
    # This import is hacky bit because of the circular import on services, handler and subscriber
    from ocpi22.cpo.mqtt.mqtt_client import MQTTClientSingleton  # noqa

    topic = _get_auth_topic_name("SMAPPEE_AUTH_RESPONSE_TOPIC")
    client = MQTTClientSingleton().get_client()
    try:
        body = payload.model_dump_json(exclude_none=True)
    except ValidationError:
        logger.exception("Failed serializing MQTT auth payload")
        return

    try:
        info = client.publish(topic, body)
        if info.rc != 0:
            logger.error("MQTT publish failed with result code %s", info.rc)
    except Exception:
        logger.exception("Failed to publish auth response to MQTT")
    return
