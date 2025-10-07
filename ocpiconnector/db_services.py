import logging
import time
from functools import wraps

from django.db import (
    InterfaceError,
    OperationalError,
    connections,
    close_old_connections,
)

from ocpiconnector.settings import env_bool
from ocpiconnector.settings.infra_services import RDSTokenManager

logger = logging.getLogger(__name__)


def ensure_db_connection(func):
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
                close_old_connections()
                repair_connection("default")
                time.sleep(0.1)
                return func(*args, **kwargs)
            raise

    return wrapper


def repair_connection(alias: str = "default"):
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
