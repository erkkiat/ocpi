import logging
import os
from typing import Union

from django.core.wsgi import get_wsgi_application
from fastapi import FastAPI
from asgiref.wsgi import WsgiToAsgi
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp
from icecream import ic

# Your ASGI app
from starlette.middleware import Middleware
from starlette.applications import Starlette


logging.basicConfig(level=logging.DEBUG)

app = FastAPI()

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ocpiconnector.settings')

django_wsgi_app = get_wsgi_application()
django_asgi_app = WsgiToAsgi(django_wsgi_app)

# Mount Django application under /django
app.mount("/d", django_asgi_app)

application = app


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.get("/items/{item_id}")
def read_item(item_id: int, q: Union[str, None] = None):
    return {"item_id": item_id, "q": q}


# Serve static files
app.mount("/static", StaticFiles(directory="staticfiles"), name="static")


@app.get("/fastapi")
async def read_root():
    return {"Hello": "World"}


class FastAPIFirstMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, fastapi_app: ASGIApp, django_app: ASGIApp):
        super().__init__(app)
        self.fastapi_app = fastapi_app
        self.django_app = django_app

    async def dispatch(self, request: Request, call_next):
        scope = request.scope
        receive = request.receive
        response = None

        async def send_wrapper(message):
            nonlocal response
            response = message
            await send(message)

        ic(scope)
        send = scope['send']

        await self.fastapi_app(scope, receive, send_wrapper)
        if response and response["type"] == "http.response.start" and response["status"] != 404:
            return Response(None, status_code=response["status"], headers=response["headers"])

        await self.django_app(scope, receive, send)
        return await call_next(request)


app.add_middleware(FastAPIFirstMiddleware, fastapi_app=app, django_app=django_asgi_app)

middleware = [
    Middleware(FastAPIFirstMiddleware, fastapi_app=app, django_app=django_asgi_app),
]

application = Starlette(middleware=middleware)
