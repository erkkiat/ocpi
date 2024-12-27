from django.db.backends.mysql.base import DatabaseWrapper as MySQLDatabaseWrapper
from django.db.utils import OperationalError
import logging

from ocpiconnector.settings.infra_services import RDSTokenManager

logger = logging.getLogger(__name__)


class DatabaseWrapper(MySQLDatabaseWrapper):
    def ensure_connection(self):
        try:
            super().ensure_connection()
        except OperationalError as e:
            if "Access denied" in str(e):
                logger.warning("Access denied. Attempting to refresh RDS token...")
                try:
                    db_url, db_user, db_token = (
                        RDSTokenManager.get_db_url_user_and_token()
                    )
                    logger.info("RDS token refreshed successfully.")
                    self.settings_dict.update(
                        {
                            "HOST": db_url,
                            "USER": db_user,
                            "PASSWORD": db_token,
                        }
                    )
                    self.connect()
                    logger.info(
                        "Reconnected to the database successfully after token refresh."
                    )
                except Exception as refresh_error:
                    logger.exception("Failed to refresh RDS token")
                    raise refresh_error
            else:
                raise e
