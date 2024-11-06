from ocpiconnector.settings.base import *  # noqa
import os

DEBUG = True
ALLOWED_HOSTS.extend(["*"])  # noqa
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

HUBJECT_URL = "https://service-qa.hubject.com/api/oicp/"

FIXIE_URL = os.getenv("FIXIE_URL", "")
os.environ["http_proxy"] = FIXIE_URL
os.environ["https_proxy"] = FIXIE_URL
os.environ["no_proxy"] = "localhost,127.0.0.1"
