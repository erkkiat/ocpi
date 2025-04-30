from ninja.throttling import AnonRateThrottle

from custom_ninja_api import CustomNinjaAPI


class HealthCheckThrottle(AnonRateThrottle):
    scope = "health_check"


health_check_api = CustomNinjaAPI(urls_namespace="health-check")


@health_check_api.get("/")
def health_check(request):
    return {"status": "Im alive"}
