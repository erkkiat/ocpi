from ocpiconnector.settings.base import *  # noqa

DEBUG = True
ALLOWED_HOSTS.extend(["*"])  # noqa
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
