import os

import boto3


def get_db_url_user_and_token():
    rds_client = boto3.client("rds", region_name="eu-west-1")
    database_url = os.getenv("DATABASE_URL")
    database_user = os.getenv("DATABASE_USER")
    if not database_url or not database_user:
        raise ValueError("Database url or user not found in the environment variable")
    token = rds_client.generate_db_auth_token(
        DBHostname=database_url,
        Port=3306,
        DBUsername=database_user,  # Your database username
    )
    return database_url, database_user, token


def get_allowed_hosts():
    allowed_hosts = os.getenv("ALLOWED_HOSTS")
    if not allowed_hosts:
        raise ValueError("Allowed hosts cannot be empty")
    hosts = allowed_hosts.split(",")
    if not hosts:
        raise ValueError("Allowed hosts cannot be empty")
    return hosts
