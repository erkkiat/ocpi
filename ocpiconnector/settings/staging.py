from ocpiconnector.settings.base import *  # noqa
import os  # noqa

ENV = os.getenv("ENV", "staging").lower()

ALLOWED_HOSTS.extend(["staging.solidroam.com"])  # noqa
MIDDLEWARE += ["silk.middleware.SilkyMiddleware"]  # noqa
# noqa
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

FIXIE_URL = os.getenv("FIXIE_URL", "")
os.environ["http_proxy"] = FIXIE_URL
os.environ["https_proxy"] = FIXIE_URL
os.environ["no_proxy"] = "localhost,127.0.0.1"
