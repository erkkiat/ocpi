import logging
import time
from functools import wraps

from django.db import (
    OperationalError as DjangoOperationalError,
    InterfaceError,
    close_old_connections,
)

logger = logging.getLogger(__name__)


def ensure_db_connection(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (DjangoOperationalError, InterfaceError) as e:
            error_msg = str(e).lower()

            if any(
                err in error_msg for err in ["server has gone away", "2006", "2013"]
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
                        f"Database retry failed in {func.__name__}: {retry_error}"
                    )
                    raise
            else:
                raise

    return wrapper
