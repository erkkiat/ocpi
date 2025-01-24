from django.http import HttpResponse
import logging
from django.conf import settings


class AllowHealthCheckMiddleware:
    """
    Middleware to allow health checks and log failures always.
    Logs successes only in DEBUG mode.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.logger = logging.getLogger(__name__)

    def __call__(self, request):
        if request.path == "/health-check/":
            # Override security settings for health checks
            request.is_secure = lambda: True

            is_healthy = self.check_health()

            if is_healthy:
                if settings.DEBUG:
                    self.logger.debug(
                        f"Health check succeeded from {request.META['HTTP_HOST']}",
                        extra=request.META,
                    )
                return HttpResponse("OK", status=200)
            else:
                # Always log failures
                self.logger.error(
                    f"Health check failed from {request.META['HTTP_HOST']}",
                    extra=request.META,
                )
                return HttpResponse("Service Unhealthy", status=500)

        return self.get_response(request)

    def check_health(self):
        """
        Add more things later
        """
        return True
