from ocpiconnector.settings.base import *  # noqa
import os  # noqa

ENV = os.getenv("ENV", "production").lower()
DEBUG = False

MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = os.getenv("MQTT_PORT")

HUBJECT_URL = "https://service.hubject.com/api/oicp/"
SMAPPEE_STATUS_UPDATE_TOPIC = os.getenv(
    "SMAPPEE_STATUS_UPDATE_TOPIC", "$share/session_group/session/+/statusupdates"
)
SMAPPEE_METER_VALUES_TOPIC = os.getenv(
    "SMAPPEE_METER_VALUES_TOPIC", "servicelocation/roaming/meter_values"
)
