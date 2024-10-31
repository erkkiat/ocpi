from ocpiconnector.settings.base import *  # noqa
import os

ALLOWED_HOSTS.extend(["staging.solidroam.com"])  # noqa
MIDDLEWARE += ["silk.middleware.SilkyMiddleware"]  # noqa
# noqa
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

FIXIE_URL = os.getenv("FIXIE_URL", "")
os.environ["http_proxy"] = FIXIE_URL
os.environ["https_proxy"] = FIXIE_URL
