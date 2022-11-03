from django.conf import settings
from rest_framework.renderers import JSONRenderer

from ocpi22.util import OnlyRawBrowsableAPIRenderer

if settings.RENDER_ONLY_JSON:
    RENDERERS = [JSONRenderer]
else:
    RENDERERS = [JSONRenderer, OnlyRawBrowsableAPIRenderer]
