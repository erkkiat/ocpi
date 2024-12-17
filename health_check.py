from ninja import NinjaAPI
from ninja.security import HttpBasicAuth


class BasicAuth(HttpBasicAuth):
    def authenticate(self, request, username, password):
        if username == "admin" and password == "secret":
            return username


health_check_api = NinjaAPI(auth=BasicAuth())


@health_check_api.get("/")
def health_check(request):
    return {"status": "Im alive"}
