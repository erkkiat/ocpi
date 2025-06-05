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
    **LOGGING,  # noqa
    "handlers": {
        **LOGGING["handlers"],  # noqa
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "loggers": {
        **LOGGING["loggers"],  # noqa
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": True,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}


LOGGING = TEST_LOGGING
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [  # noqa
    "rest_framework.renderers.JSONRenderer",
]
