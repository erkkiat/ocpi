from ocpiconnector.settings.base import *  # noqa
import os  # noqa

from ocpiconnector.settings.infra_services import (
    get_allowed_hosts,
    RDSTokenManager,
)

ENV = os.getenv("ENV", "staging").lower()
DEBUG = os.getenv("DEBUG", False)
ALLOWED_HOSTS = get_allowed_hosts()
HUBJECT_URL = "https://service-qa.hubject.com/api/oicp/"
MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtttest.smappee.net")
MQTT_PORT = os.getenv("MQTT_PORT", 443)
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
MQTT_SSL_VERIFY = os.getenv("MQTT_SSL_VERIFY", True)

FIXIE_URL = os.getenv("FIXIE_URL", "")
os.environ["http_proxy"] = FIXIE_URL
os.environ["https_proxy"] = FIXIE_URL
os.environ["no_proxy"] = "localhost,127.0.0.1"

SMAPPEE_STATUS_UPDATE_TOPIC = os.getenv(
    "SMAPPEE_STATUS_UPDATE_TOPIC", "$share/session_group/session/+/statusupdates"
)
SMAPPEE_METER_VALUES_TOPIC = os.getenv(
    "SMAPPEE_METER_VALUES_TOPIC", "servicelocation/roaming/meter_values"
)

db_url, db_user, db_token = RDSTokenManager.get_db_url_user_and_token()
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": "ocpi",
        "USER": db_user,
        "PASSWORD": db_token,
        "HOST": db_url,
        "PORT": "3306",
        "OPTIONS": {"ssl_mode": "REQUIRED"},
    }
}
