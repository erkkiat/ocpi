from ocpiconnector.settings.base import *  # noqa
import os  # noqa

ENV = os.getenv("ENV", "staging").lower()
DEBUG = os.getenv("DEBUG", False)
HUBJECT_URL = "https://service-qa.hubject.com/api/oicp/"

ALLOWED_HOSTS.extend(["staging.solidroam.com"])  # noqa
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

FIXIE_URL = os.getenv("FIXIE_URL", "")
os.environ["http_proxy"] = FIXIE_URL
os.environ["https_proxy"] = FIXIE_URL
os.environ["no_proxy"] = "localhost,127.0.0.1"

SMAPPEE_STATUS_UPDATE_TOPIC = os.getenv(
    "SMAPPEE_STATUS_UPDATE_TOPIC", "$share/session_group/session/+/statusupdates"
)
SMAPPEE_METER_VALUES_TOPIC = os.getenv(
    "SMAPPEE_METER_VALUES_TOPIC", "$share/session_group/session/+/metervalues"
)
