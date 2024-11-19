import os
from logging import getLogger

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.celery import CeleryIntegration

logger = getLogger("__name__")


def setup_sentry():
    sentry_dsn = os.getenv("SENTRY_DSN")
    env = os.getenv("ENV", "development").lower()
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
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
        ],
        traces_sample_rate=tracing_sampling_rate,  # Adjust based on your needs
        profiles_sample_rate=profiling_sample_rate,
        send_default_pii=True,
    )
