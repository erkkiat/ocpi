from django.http import HttpResponse
import logging
import ipaddress
from django.conf import settings
from django.core.exceptions import DisallowedHost


class AllowHealthCheckMiddleware:
    """
    Middleware to allow health checks and log failures always.
    Logs successes only in DEBUG mode.
    Handles AWS Load Balancer health checks from private IPs.
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
                        f"Health check succeeded from {request.META.get('HTTP_HOST', 'unknown')}",
                        extra=request.META,
                    )
                return HttpResponse("OK", status=200)
            else:
                self.logger.error(
                    f"Health check failed from {request.META.get('HTTP_HOST', 'unknown')}",
                    extra=request.META,
                )
                return HttpResponse("Service Unhealthy", status=500)

        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, DisallowedHost) and request.path == "/health-check/":
            client_ip = self.get_client_ip(request)
            if client_ip and self.is_private_ip(client_ip):
                if settings.DEBUG:
                    self.logger.debug(
                        f"Allowing health check from private IP: {client_ip}",
                        extra={"client_ip": client_ip, "path": request.path},
                    )
                is_healthy = self.check_health()
                return HttpResponse(
                    "OK" if is_healthy else "Service Unhealthy",
                    status=200 if is_healthy else 500,
                )
        return None

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            ip = request.META.get("REMOTE_ADDR")
        return ip

    def is_private_ip(self, ip):
        try:
            ip_obj = ipaddress.ip_address(ip)
            return ip_obj.is_private
        except ValueError:
            return False

    def check_health(self):
        """
        Add more things later
        """
        return True
