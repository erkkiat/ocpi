import os
from logging import getLogger

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.celery import CeleryIntegration

logger = getLogger("__name__")


def before_send(event, hint):
    request = event.get("request", {})
    url = request.get("url", "")
    if url.endswith("/health-check/"):
        return None  # Drop the event
    return event


def setup_sentry():
    sentry_dsn = os.getenv("SENTRY_DSN")
    env = os.getenv("ENV", "development").lower()
    service_name = os.getenv("SENTRY_SERVICE_NAME", "django-app")
    tracing_sampling_rate = float(os.getenv("SENTRY_TRACING_SAMPLING_RATE", 0.2))
    profiling_sample_rate = float(os.getenv("SENTRY_PROFILING_SAMPLING_RATE", 0.2))
    if env in ["development", "test"]:
        logger.info(f"Skipping Sentry initialization in {env} environment")
        return
    if not sentry_dsn:
        logger.warning(f"SENTRY_DSN not set for {env}, Please set it to enable Sentry")
        return
    sentry_sdk.init(
        dsn=sentry_dsn,
        before_send=before_send,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
        ],
        environment=env,
        traces_sample_rate=tracing_sampling_rate,  # Adjust based on your needs
        profiles_sample_rate=profiling_sample_rate,
        send_default_pii=False,
    )
    sentry_sdk.set_tag("service_name", service_name)
