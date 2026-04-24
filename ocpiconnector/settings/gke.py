import ssl
from distutils.util import strtobool

from ocpiconnector.settings.base import *  # noqa
import os  # noqa

from ocpiconnector.settings.infra_services import (
    get_allowed_hosts,
    configure_database,
)

ENV = os.getenv("ENV", "staging").lower()
DEBUG = strtobool(os.getenv("DEBUG", "False"))

# Hubject — URL and hosts must be set per environment via configmap/secrets
HUBJECT_URL = os.getenv("HUBJECT_URL", "https://service.hubject.com/api/oicp/")
HUBJECT_HOSTS = [
    # staging
    "18.195.149.69",
    "18.195.61.108",
    # production
    "18.194.114.107",
    "35.157.60.250",
]

CSRF_TRUSTED_ORIGINS = os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
ALLOWED_HOSTS = get_allowed_hosts()

USE_X_FORWARDED_PORT = True
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PROTO = True
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

MQTT_BROKER = os.getenv("MQTT_BROKER", "")
MQTT_PORT = os.getenv("MQTT_PORT", 8085)
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_USE_SSL = os.getenv("MQTT_USE_SSL", False)

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

DATABASES = configure_database()

HUBJECT_EMP_ID = os.getenv("HUBJECT_EMP_ID", "DE*ICE")

STATICFILES_STORAGE = "ocpiconnector.storage.LenientManifestStaticFilesStorage"
WHITENOISE_MAX_AGE = 31536000  # 1 year

_cdn_url = os.environ.get("STATIC_CDN_URL", "")
if _cdn_url:
    STATIC_URL = _cdn_url.rstrip("/") + "/static/"
