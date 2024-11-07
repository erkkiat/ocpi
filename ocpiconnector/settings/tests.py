from ocpiconnector.settings.base import *  # noqa
import os  # noqa

ALLOWED_HOSTS.extend(["*"])  # noqa
SEND_DATA_TO_ANALYTICS = (
    True  # This is not needed, will refactor after the settings refactor
)
DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgres://ocpi:ocpiocpi@localhost:5432/test_db"
)
