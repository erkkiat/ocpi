from ocpiconnector.settings.dev import *  # noqa
import os  # noqa

ENV = os.getenv("ENV", "test").lower()
HOSTNAME = "testserver.test"  # Remove this hostname later once the allowed hosts is configured nicely

ALLOWED_HOSTS = ["testserver.test", "localhost", "127.0.0.1"]
# noqa
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgres://test_user:test_password@localhost:5432/test_db"
)
SECRET_KEY = "BESTONEEVER"

TEST_LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "ocpiconnector.logging_middleware.ORJSONFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "ocpi22.cpo.mqtt.mqtt_subscriber": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "__main__": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}


LOGGING = TEST_LOGGING
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [  # noqa
    "rest_framework.renderers.JSONRenderer",
]
