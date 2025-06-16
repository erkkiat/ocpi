import os
from logging import getLogger

from pydantic import ValidationError

from ocpi22.cpo.mqtt.schemas import TokenAuthorizationResponse

logger = getLogger(__name__)


def _get_auth_topic_name(topi_env_ar: str):
    topic = os.getenv(topi_env_ar)
    if topic and "$share" in topic:
        return "/".join(topic.split("/")[2:])
    else:
        return "servicelocation/roaming/authresponse"


def publish_auth_response(payload: TokenAuthorizationResponse):
    # This is still hacky, because of process_authorize_data importing publisher
    from ocpi22.cpo.mqtt.mqtt_client import MQTTClientSingleton

    topic = _get_auth_topic_name("SMAPPEE_AUTH_RESPONSE")
    try:
        payload = payload.model_dump_json(exclude_unset=True)
    except ValidationError:
        MQTTClientSingleton().get_client().publish(topic, payload)
        return
    except Exception:
        logger.exception("Publishing auth response failed miserably")
        return
