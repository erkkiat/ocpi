import logging

from django.http import HttpResponse

logger = logging.getLogger(__name__)


class AllowHealthCheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/health-check/":
            logging.info(
                f"Health check from {request.META['HOST']}", extra=request.META
            )
            return HttpResponse("OK", status=200)
        return self.get_response(request)
