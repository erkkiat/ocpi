import logging

from celery import Task
from celery.signals import worker_process_init
from django.db.utils import OperationalError
from django.db import connections

from ocpiconnector.settings import env_bool
from ocpiconnector.settings.infra_services import RDSTokenManager

logger = logging.getLogger(__name__)


class RefreshTokenBaseTask(Task):
    """
    Custom Celery base task that:
    - Refreshes RDS token before task execution
    - Automatically retries on OperationalError
    """

    autoretry_for = (OperationalError,)
    retry_backoff = True
    retry_kwargs = {"max_retries": 3}

    def before_start(self, task_id, args, kwargs):
        """
        Refresh the RDS token if needed before the task runs.
        """
        if not env_bool("REFRESH_RDS_TOKEN_FOR_TASKS", True):
            return super().before_start(task_id, args, kwargs)

        try:
            connections["default"].ensure_connection()
        except OperationalError:
            _, _, token = RDSTokenManager.get_db_url_user_and_token()
            logger.warning(
                "DB connection issue before task start. Refreshing RDS token."
            )
            connections["default"].settings_dict["PASSWORD"] = token

        return super().before_start(task_id, args, kwargs)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.exception(f"Task {self.name} failed")
        return super().on_failure(exc, task_id, args, kwargs, einfo)


@worker_process_init.connect
def setup_worker_connection(**kwargs):
    """Ensure each worker process uses the latest RDS token."""
    if not env_bool("REFRESH_RDS_TOKEN_FOR_TASKS", True):
        return
    _, _, token = RDSTokenManager.get_db_url_user_and_token()
    connection = connections["default"]
    connection.settings_dict["PASSWORD"] = token
