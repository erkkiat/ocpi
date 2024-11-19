from ocpiconnector.settings.base import *  # noqa
import os  # noqa

ENV = os.getenv("ENV", "test").lower()
HOSTNAME = "testserver.test" # Remove this hostname later once the allowed hosts is configured nicely

ALLOWED_HOSTS = ['testserver.test', 'localhost', '127.0.0.1']
# noqa
SEND_DATA_TO_ANALYTICS = (
    True  # This is not needed, will refactor after the settings refactor
)
DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgres://ocpi:ocpiocpi@localhost:5432/test_db"
)
SECRET_KEY="BESTONEEVER"
