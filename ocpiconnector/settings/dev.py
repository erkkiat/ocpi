from distutils.util import strtobool

from ocpiconnector.settings.base import *  # noqa
import os  # noqa
from urllib.parse import urlparse

ENV = os.getenv("ENV", "development").lower()

HUBJECT_HOSTS = ["18.195.149.69", "18.195.61.108"]
DEBUG = strtobool(os.getenv("DEBUG", "True"))
ALLOWED_HOSTS.extend(["*"])  # noqa
MQTT_BROKER = os.getenv("MQTT_BROKER", "emqx")
MQTT_PORT = os.getenv("MQTT_PORT", 1883)
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
MQTT_USE_SSL = os.getenv("MQTT_USE_SSL", False)

HUBJECT_URL = "https://service-qa.hubject.com/api/oicp/"

FIXIE_URL = os.getenv("FIXIE_URL", "")

SMAPPEE_STATUS_UPDATE_TOPIC = os.getenv(
    "SMAPPEE_STATUS_UPDATE_TOPIC", "$share/session_group/session/+/statusupdates"
)
SMAPPEE_METER_VALUES_TOPIC = os.getenv(
    "SMAPPEE_METER_VALUES_TOPIC", "$share/session_group/session/+/statusupdates"
)

#  Refactor this
url = urlparse(DATABASE_URL)  # noqa

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql"
        if url.scheme == "postgres"
        else "django.db.backends.mysql",
        "NAME": url.path[1:],  # Remove the leading '/'
        "USER": url.username,
        "PASSWORD": url.password,
        "HOST": url.hostname,
        "PORT": url.port,
    }
}

DATABASES.update({"gdpr_log": DATABASES.get("default")})

HUBJECT_EMP_ID = os.getenv("HUBJECT_EMP_ID", "DE*ICE")

PTP_CUSTOMER_REFERENCE = os.getenv("PTP_CUSTOMER_REFERENCE", "TEST-CUSTOMER-REF")
