from ocpiconnector.settings.base import *  # noqa
import os  # noqa
from urllib.parse import urlparse

ENV = os.getenv("ENV", "development").lower()

DEBUG = os.getenv("DEBUG").lower() in ("1", "true", "yes")
ALLOWED_HOSTS.extend(["*"])  # noqa
MQTT_BROKER = os.getenv("MQTT_BROKER", "emqx")
MQTT_PORT = os.getenv("MQTT_PORT", 1883)
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
MQTT_SSL_VERIFY = os.getenv("MQTT_SSL_VERIFY", False)

HUBJECT_URL = "https://service-qa.hubject.com/api/oicp/"

FIXIE_URL = os.getenv("FIXIE_URL", "")
os.environ["http_proxy"] = FIXIE_URL
os.environ["https_proxy"] = FIXIE_URL
os.environ["no_proxy"] = "localhost,127.0.0.1"

SMAPPEE_STATUS_UPDATE_TOPIC = os.getenv(
    "SMAPPEE_STATUS_UPDATE_TOPIC", "$share/session_group/session/+/statusupdates"
)
SMAPPEE_METER_VALUES_TOPIC = os.getenv(
    "SMAPPEE_METER_VALUES_TOPIC", "$share/session_group/session/+/statusupdates"
)
DEV_LOGGING = {
    **LOGGING,  # noqa
    "loggers": {
        **LOGGING["loggers"],  # noqa
        "django": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": True,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "ocpi22.cpo.mqtt.mqtt_subscriber": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": True,
        },
    },
}

LOGGING = DEV_LOGGING
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
