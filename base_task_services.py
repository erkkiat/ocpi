import logging
from functools import wraps

from celery import Task, signals
from django.db import connections, close_old_connections
from django.db.utils import OperationalError, InterfaceError

from ocpiconnector.settings import env_bool
from ocpiconnector.settings.infra_services import RDSTokenManager

logger = logging.getLogger(__name__)


@signals.worker_process_init.connect
def initialize_worker_database_connections(**kwargs):
    logger.info("Worker process initializing - closing inherited DB connections")

    for conn in connections.all():
        try:
            conn.close()
        except Exception as e:
            logger.warning(f"Error closing connection during worker init: {e}")

    logger.info("Worker process initialized with clean connection state")


@signals.worker_process_shutdown.connect
def shutdown_worker_database_connections(**kwargs):
    logger.info("Shutting down worker process - closing DB connections")
    close_old_connections()


@signals.task_prerun.connect
def setup_task_database_connections(**kwargs):
    close_old_connections()


@signals.task_postrun.connect
def cleanup_task_database_connections(**kwargs):
    close_old_connections()


class DatabaseTask(Task):
    autoretry_for = (
        OperationalError,
        InterfaceError,
    )

    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True
    max_retries = 3

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        logger.warning(
            f"Task {self.name} retrying due to database error",
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
            extra={
                "task_id": task_id,
                "exception": str(exc),
            },
            exc_info=True,
        )
        return super().on_failure(exc, task_id, args, kwargs, einfo)


class RDSIAMTokenMixin:
    def before_start(self, task_id, args, kwargs):
        if env_bool("REFRESH_RDS_TOKEN_FOR_TASKS", True):
            self._ensure_rds_token_is_fresh()

        return super().before_start(task_id, args, kwargs)

    def _ensure_rds_token_is_fresh(self):
        connection = connections["default"]

        if connection.connection is not None:
            try:
                connection.ensure_connection()
                logger.debug("Database connection healthy, skipping token refresh")
                return
            except (OperationalError, InterfaceError) as e:
                logger.info(
                    f"Database connection unhealthy: {e}. Refreshing RDS token."
                )

        try:
            db_url, user, token = RDSTokenManager.get_db_url_user_and_token()
            connection.settings_dict["PASSWORD"] = token
            connection.close()
            close_old_connections()

            logger.info("RDS IAM token refreshed successfully")

        except Exception as e:
            logger.error(f"Failed to refresh RDS IAM token: {e}")


class RefreshTokenBaseTask(RDSIAMTokenMixin, DatabaseTask):
    pass


def ensure_db_connection(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        import time

        try:
            return func(*args, **kwargs)
        except (OperationalError, InterfaceError) as e:
            error_msg = str(e).lower()

            if any(
                err in error_msg
                for err in [
                    "server has gone away",
                    "2006",
                    "2013",
                    "connection",
                    "lost",
                ]
            ):
                logger.warning(
                    f"Database connection lost in {func.__name__}, retrying once: {e}"
                )

                close_old_connections()
                time.sleep(0.1)

                try:
                    return func(*args, **kwargs)
                except Exception as retry_error:
                    logger.error(
                        f"Database retry failed in {func.__name__}: {retry_error}",
                        exc_info=True,
                    )
                    raise
            else:
                raise

    return wrapper
