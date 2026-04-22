"""
Minimal Django settings for running collectstatic at Docker build time.

No database, no Redis, no external services required.
Used only by: RUN python manage.py collectstatic --noinput  (Dockerfile)
"""

import os

# Allow base.py to load without failing on missing env vars
os.environ.setdefault("SECRET_KEY", "collectstatic-build-only-not-for-runtime")

from ocpiconnector.settings.base import *  # noqa

# Disable all external service connections — not needed for collectstatic
DATABASES = {}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
