# ocpiconnector/celery_db_base.py

import logging
import time
from functools import wraps

from celery import Task
from celery import signals as celery_signals
from django.db import connections, close_old_connections
from django.db.utils import OperationalError, InterfaceError

from ocpiconnector.settings import env_bool
from ocpiconnector.settings.infra_services import RDSTokenManager

logger = logging.getLogger(__name__)


def _repair_connection(alias: str = "default"):
    conn = connections[alias]
    try:
        conn.ensure_connection()
        return
    except (OperationalError, InterfaceError):
        pass

    if env_bool("REFRESH_RDS_TOKEN_FOR_TASKS", True):
        try:
            _, _, token = RDSTokenManager.get_db_url_user_and_token()
            conn.settings_dict["PASSWORD"] = token
        except Exception as e:
            logger.warning(f"RDS token refresh failed (continuing reopen): {e}")

    try:
        conn.close()
    except Exception:
        pass

    close_old_connections()
    conn.ensure_connection()


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
                _repair_connection("default")
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


def ensure_db_connection(func):
    """
    For long-lived runners (e.g., MQTT handlers): on connection-loss errors,
    repair the connection and retry once. No-op on healthy connections.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (OperationalError, InterfaceError) as e:
            msg = str(e).lower()
            if any(
                s in msg
                for s in (
                    "server has gone away",
                    "2006",
                    "2013",
                    "connection",
                    "lost",
                    "closed",
                    "reset by peer",
                    "broken pipe",
                    "terminating connection",
                    "ssl syscall",
                )
            ):
                logger.warning(
                    f"{func.__name__}: DB issue detected; repairing and retrying once: {e}"
                )
                _repair_connection("default")
                time.sleep(0.1)
                return func(*args, **kwargs)
            raise

    return wrapper
