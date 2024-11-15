from ocpiconnector.settings.base import *  # noqa
import os  # noqa

ENV = os.getenv("ENV", "development").lower()

DEBUG = True
ALLOWED_HOSTS.extend(["*"])  # noqa
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

SMAPPEE_STATUS_UPDATE_TOPIC = os.getenv("SMAPPEE_STATUS_UPDATE_TOPIC", "$share/session_group/session/+/statusupdates")
SMAPPEE_METER_VALUES_TOPIC = os.getenv("SMAPPEE_METER_VALUES_TOPIC", "$share/session_group/session/+/statusupdates")
