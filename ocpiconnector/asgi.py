import os
from django.core.asgi import get_asgi_application
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi_app.main import app as fastapi_app

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ocpiconnector.settings")

django_app = get_asgi_application()
fastapi_app.mount("/django", WSGIMiddleware(django_app))

# Mount FastAPI application under /
fastapi_app.include_router(fastapi_app.router)

application = fastapi_app
