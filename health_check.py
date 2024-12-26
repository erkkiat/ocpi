from ninja import NinjaAPI
from ninja.throttling import AnonRateThrottle


class HealthCheckThrottle(AnonRateThrottle):
    scope = "health_check"


health_check_api = NinjaAPI(urls_namespace="health-check")


@health_check_api.get("/")
def health_check(request):
    return {"status": "Im alive"}
