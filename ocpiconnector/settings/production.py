from ocpiconnector.settings.base import *  # noqa
import os  # noqa

from ocpiconnector.settings.infra_services import get_db_url_user_and_token

ENV = os.getenv("ENV", "production").lower()
DEBUG = False
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(",")

SECURE_SSL_REDIRECT = True

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

SECURE_HSTS_SECONDS = 31536000  # Enforce HTTPS for 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

SECURE_CONTENT_TYPE_NOSNIFF = True

X_FRAME_OPTIONS = "DENY"

SECURE_REFERRER_POLICY = "same-origin"


HUBJECT_URL = "Add the hubject production base url"


ALLOWED_HOSTS.extend(["*.smappee.com"])  # noqa
MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = os.getenv("MQTT_PORT", 443)
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
MQTT_SSL_VERIFY = os.getenv("MQTT_SSL_VERIFY", True)

SMAPPEE_STATUS_UPDATE_TOPIC = os.getenv(
    "SMAPPEE_STATUS_UPDATE_TOPIC", "$share/session_group/session/+/statusupdates"
)
SMAPPEE_METER_VALUES_TOPIC = os.getenv(
    "SMAPPEE_METER_VALUES_TOPIC", "servicelocation/roaming/meter_values"
)

db_url, db_user, db_token = get_db_url_user_and_token()
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": "ocpi",
        "USER": db_user,
        "PASSWORD": db_token,
        "HOST": db_url,
        "PORT": "3306",
    }
}
