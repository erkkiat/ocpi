import logging
from celery import Task
from celery.signals import worker_process_init
from django.db.utils import OperationalError
from django.db import connections

from ocpiconnector.settings.infra_services import RDSTokenManager

logger = logging.getLogger(__name__)


class RefreshTokenBaseTask(Task):
    """Base task to be used by rest of the tasks, mainly handles the db token and refresh
    when there is a connection failure due to the the expired/invalid token"""

    autoretry_for = (OperationalError,)
    retry_backoff = 5
    max_retries = 3

    def __call__(self, *args, **kwargs):
        try:
            return super().__call__(*args, **kwargs)
        except self.autoretry_for as exc:
            retries = self.request.retries
            if retries < self.max_retries:
                countdown = self.retry_backoff * (retries + 1)
                logger.warning(
                    f"Task {self.name} failed with {exc}. Retrying in {countdown} seconds "
                    f"(attempt {retries + 1}/{self.max_retries})"
                )
                raise self.retry(exc=exc, countdown=countdown)
            else:
                logger.error(
                    f"Task {self.name} failed after {self.max_retries} retries."
                )
                raise

    def before_start(self, task_id, args, kwargs):
        """Refresh the database connection before starting the task."""
        try:
            connections["default"].ensure_connection()
        except OperationalError:
            _, _, token = RDSTokenManager.get_db_url_user_and_token()
            logger.warning(
                "Database connection issue detected before task start. Retrying..."
            )
            connections["default"].settings_dict["PASSWORD"] = token
        super().before_start(task_id, args, kwargs)


@worker_process_init.connect
def setup_worker_connection(**kwargs):
    """Ensure each worker process uses the latest RDS token."""
    _, _, token = RDSTokenManager.get_db_url_user_and_token()
    connection = connections["default"]
    connection.settings_dict["PASSWORD"] = token
