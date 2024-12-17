import os

from ninja import NinjaAPI
from ninja.security import HttpBasicAuth


class BasicAuth(HttpBasicAuth):
    def authenticate(self, request, username, password):
        set_user = os.getenv("HEALTH-CHECK-USER")
        set_password = os.getenv("HEALTH-CHECK-PASSWORD")
        if username == set_user and password == set_password:
            return username


health_check_api = NinjaAPI(auth=BasicAuth())


@health_check_api.get("/")
def health_check(request):
    return {"status": "Im alive"}
