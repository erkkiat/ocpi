import ssl
from distutils.util import strtobool

from ocpiconnector.settings.base import *  # noqa
import os  # noqa

from ocpiconnector.settings.infra_services import (
    get_allowed_hosts,
    RDSTokenManager,
)

ENV = os.getenv("ENV", "staging").lower()
DEBUG = strtobool(os.getenv("DEBUG", "False"))

HUBJECT_HOSTS = ["18.195.149.69", "18.195.61.108"]
ALLOWED_HOSTS = get_allowed_hosts() + HUBJECT_HOSTS
USE_X_FORWARDED_PORT = True
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PROTO = True
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 300  # Enforce HTTPS for 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

HUBJECT_URL = os.getenv("HUBJECT_URL", "https://service-qa.hubject.com/api/oicp/")
MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtttest.smappee.net")
MQTT_PORT = os.getenv("MQTT_PORT", 443)
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
MQTT_USE_SSL = os.getenv("MQTT_USE_SSL", False)

CSRF_TRUSTED_ORIGINS = ["https://solidroam.f3-smappee.net"]

SMAPPEE_STATUS_UPDATE_TOPIC = os.getenv(
    "SMAPPEE_STATUS_UPDATE_TOPIC", "$share/session_group/session/+/statusupdates"
)
SMAPPEE_METER_VALUES_TOPIC = os.getenv(
    "SMAPPEE_METER_VALUES_TOPIC", "servicelocation/roaming/meter_values"
)

REDIS_URL = os.environ["REDIS_URL"]
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"SSL": True, "SSL_CERT_REQS": ssl.CERT_NONE},
    },
}

db_url, db_user, db_token = RDSTokenManager.get_db_url_user_and_token()
DATABASES = {
    "default": {
        "ENGINE": "ocpiconnector.db_backends.mysql",
        "NAME": "ocpi",
        "USER": db_user,
        "PASSWORD": db_token,
        "HOST": db_url,
        "PORT": "3306",
        "OPTIONS": {"ssl_mode": "REQUIRED"},
        "CONN_MAX_AGE": 200,
        "CONN_HEALTH_CHECKS": True,
    }
}

HUBJECT_EMP_ID = os.getenv("HUBJECT_EMP_ID", "DE*ICE")
