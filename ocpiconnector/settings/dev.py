from ocpiconnector.settings.base import *  # noqa
import os  # noqa

ENV = os.getenv("ENV", "development").lower()

DEBUG = os.getenv("DEBUG", True)
ALLOWED_HOSTS.extend(["*"])  # noqa
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

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
