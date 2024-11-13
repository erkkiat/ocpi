from ocpiconnector.settings.base import *  # noqa
import sentry_sdk


ALLOWED_HOSTS.extend(["*"])  # noqa
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
SEND_DATA_TO_ANALYTICS = (
    True  # This is not needed, will refactor after the settings refactor
)

sentry_sdk.init(dsn=None)
