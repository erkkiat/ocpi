from ocpiconnector.settings.base import *  # noqa
import os  # noqa

ENV = os.getenv("ENV", "development").lower()

DEBUG = True
ALLOWED_HOSTS.extend(["*"])  # noqa
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
