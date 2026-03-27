import os
import socket
import uuid
from logging import getLogger
from urllib.parse import urlparse

import boto3
import time
import threading

import pythonjsonlogger

logger = getLogger(__name__)


def get_allowed_hosts():
    allowed_hosts = os.getenv("ALLOWED_HOSTS")
    if not allowed_hosts:
        raise ValueError("Allowed hosts cannot be empty")
    hosts = allowed_hosts.split(",")
    if not hosts:
        raise ValueError("Allowed hosts cannot be empty")
    return hosts


class RDSTokenManager:
    """Manages RDS token generation and caching."""

    _token = None
    _token_expiry = 0
    _lock = threading.Lock()

    @classmethod
    def get_db_url_user_and_token(cls):
        """Get the current RDS token or refresh it if expired."""

        database_url = os.getenv("DATABASE_URL")
        database_user = os.getenv("DATABASE_USER")
        if not database_url or not database_user:
            raise ValueError(
                "Database url or user not found in the environment variable"
            )

        with cls._lock:
            current_time = time.time()
            if cls._token is None or current_time >= cls._token_expiry - 60:
                # Refresh the token 1 minute before expiration
                rds_client = boto3.client("rds", region_name="eu-west-1")
                cls._token = rds_client.generate_db_auth_token(
                    DBHostname=database_url,
                    Port=3306,
                    DBUsername=database_user,
                )
                cls._token_expiry = current_time + 12 * 60
            return database_url, database_user, cls._token


class CustomJsonFormatter(pythonjsonlogger.json.JsonFormatter):
    def add_fields(self, log_record, record, message_dict=None):
        super().add_fields(log_record, record, message_dict)
        log_record["docker_id"] = socket.gethostname()
        log_record["event_id"] = str(uuid.uuid4())


def configure_database():
    database_url = os.getenv("DATABASE_URL")
    assert database_url, "Database URL must be set in environment variables"
    parsed_url = urlparse(database_url)

    if parsed_url.scheme == "mysql":
        db_url, db_user, db_token = RDSTokenManager.get_db_url_user_and_token()
        engine = "django.db.backends.mysql"
        user = db_user
        password = db_token
        host = db_url
        port = 3306
        options = {"ssl_mode": "REQUIRED"}
    else:
        engine = "django.db.backends.postgresql"
        user = parsed_url.username
        password = parsed_url.password
        host = parsed_url.hostname
        port = parsed_url.port
        options = {"sslmode": "require"}

    database = {
        "default": {
            "ENGINE": engine,
            "NAME": "ocpi",
            "USER": user,
            "PASSWORD": password,
            "HOST": host,
            "PORT": port,
            "CONN_MAX_AGE": 300,
            "OPTIONS": options,
            "CONN_HEALTH_CHECKS": True,
        }
    }
    return database
