import logging

logger = logging.getLogger("django")


class LogHostHeaderMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        logger.info(f"DEBUG: Received Host header: {request.get_host()}")
        return self.get_response(request)
