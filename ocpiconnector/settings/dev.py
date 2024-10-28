from ocpiconnector.settings.base import *  # noqa

DEBUG = True
ALLOWED_HOSTS.extend(["*"])  # noqa
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

HUBJECT_URL = "https://service-qa.hubject.com/api/oicp/"
# HUBJECT_URL = "https://cdce596d-2955-4ae7-988d-94f4adf06fbc.mock.pstmn.io"
