from ocpiconnector.settings.base import *  # noqa
import os  # noqa

ENV = os.getenv("ENV", "production").lower()
DEBUG = False

HUBJECT_URL = "https://service.hubject.com/api/oicp/"
