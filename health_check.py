import os

from ninja import NinjaAPI
from ninja.security import HttpBasicAuth
from ninja.throttling import AnonRateThrottle


class HealthCheckThrottle(AnonRateThrottle):
    scope = "health_check"


class BasicAuth(HttpBasicAuth):
    def authenticate(self, request, username, password):
        set_user = os.getenv("HEALTH-CHECK-USER")
        set_password = os.getenv("HEALTH-CHECK-PASSWORD")
        if not set_user or not set_password:
            raise ValueError("Health check auth are not set please set it first")
        if username == set_user and password == set_password:
            return username


health_check_api = NinjaAPI(auth=BasicAuth())


@health_check_api.get("/")
def health_check(request):
    return {"status": "Im alive"}
