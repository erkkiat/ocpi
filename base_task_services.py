# ocpiconnector/celery_db_base.py

import logging

from celery import Task
from celery import signals as celery_signals
from django.db import connections
from django.db.utils import OperationalError, InterfaceError

from ocpiconnector.db_services import repair_connection
from ocpiconnector.settings import env_bool
from ocpiconnector.settings.infra_services import RDSTokenManager

logger = logging.getLogger(__name__)


@celery_signals.worker_process_init.connect
def setup_worker_connection(**kwargs):
    if not env_bool("REFRESH_RDS_TOKEN_FOR_TASKS", True):
        return
    try:
        _, _, token = RDSTokenManager.get_db_url_user_and_token()
        connections["default"].settings_dict["PASSWORD"] = token
        logger.info("Initialized worker with latest RDS IAM token")
    except Exception as e:
        logger.warning(f"Could not initialize RDS token on worker init: {e}")


class RefreshTokenBaseTask(Task):
    """
    Celery base task:
    - Ensures fresh RDS IAM token before start
    - Retries automatically on DB connection errors
    """

    autoretry_for = (OperationalError, InterfaceError)
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True
    max_retries = 3

    def before_start(self, task_id, args, kwargs):
        if env_bool("REFRESH_RDS_TOKEN_FOR_TASKS", True):
            try:
                repair_connection("default")
            except Exception as e:
                logger.warning(f"Failed to ensure DB connection before task: {e}")
        return super().before_start(task_id, args, kwargs)

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        logger.warning(
            f"Task {self.name} retrying due to DB error",
            extra={
                "task_id": task_id,
                "exception": str(exc),
                "retry_count": self.request.retries,
                "max_retries": self.max_retries,
            },
        )
        return super().on_retry(exc, task_id, args, kwargs, einfo)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(
            f"Task {self.name} failed after {self.request.retries} retries",
            extra={"task_id": task_id, "exception": str(exc)},
            exc_info=True,
        )
        return super().on_failure(exc, task_id, args, kwargs, einfo)
