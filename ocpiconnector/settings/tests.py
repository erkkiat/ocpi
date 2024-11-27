from ocpiconnector.settings.dev import *  # noqa
import os  # noqa

ENV = os.getenv("ENV", "test").lower()
HOSTNAME = "testserver.test"  # Remove this hostname later once the allowed hosts is configured nicely

ALLOWED_HOSTS = ["testserver.test", "localhost", "127.0.0.1"]
# noqa
SEND_DATA_TO_ANALYTICS = (
    True  # This is not needed, will refactor after the settings refactor
)
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgres://test_user:test_password@localhost:5432/test_db"
)
SECRET_KEY = "BESTONEEVER"


TEST_LOGGING = {
    **LOGGING,  # noqa
    "handlers": {
        **LOGGING["handlers"],  # noqa
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        **LOGGING["loggers"],  # noqa
        "django": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": True,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "ocpi22.cpo.mqtt.mqtt_subscriber": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,  # Prevent log propagation to isolate caplog behavior
        },
    },
}

LOGGING = TEST_LOGGING
