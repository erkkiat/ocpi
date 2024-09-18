from ocpiconnector.settings.base import *  # noqa

ALLOWED_HOSTS.extend(["staging.solidroam.com"])  # noqa
MIDDLEWARE += ["silk.middleware.SilkyMiddleware"]  # noqa
