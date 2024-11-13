from ocpiconnector.settings.base import *  # noqa
import sentry_sdk


DEBUG = True
ALLOWED_HOSTS.extend(["*"])  # noqa
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

sentry_sdk.init(dsn=None)
