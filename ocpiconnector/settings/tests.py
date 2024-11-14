from ocpiconnector.settings.base import *  # noqa
import os  # noqa

ENV = os.getenv("ENV", "test").lower()

ALLOWED_HOSTS.extend(["*"])  # noqa
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
SEND_DATA_TO_ANALYTICS = (
    True  # This is not needed, will refactor after the settings refactor
)
DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgres://ocpi:ocpiocpi@localhost:5432/ocpiconnector_test"
)
