import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ocpiconnector.settings")

django_app = get_asgi_application()
