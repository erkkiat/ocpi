import time
import uuid
from http import HTTPStatus
from logging import getLogger

import orjson
from django.utils.deprecation import MiddlewareMixin


class LoggingMiddleware(MiddlewareMixin):
    def __init__(self, get_response):
        super(LoggingMiddleware, self).__init__(get_response)
        self.get_response = get_response
        self.logger = getLogger(__name__)
        self.cleaned_payload = None
        self.exception = None

    def process_request(self, request):
        request.start_time = time.time()
        self.cleaned_payload = self.get_cleaned_payload(request)
        return None

    def process_response(self, request, response):
        response_time = time.time() - request.start_time
        request_data = self.get_request_data(request)
        response_data = self.get_response_data(response, response_time)
        extra_data = {**request_data, **response_data}
        message = extra_data["uri"] + " " + extra_data["response_message"]
        if not self.exception:
            self.logger.info(
                message,
                extra=extra_data,
            )
        else:
            self.logger.error(
                message,
                extra=extra_data,
                exc_info=self.exception,
            )
        self.exception = None
        return response

    def process_exception(self, request, exception):
        self.logger.info("This is the exception", exc_info=exception)
        self.exception = exception
        return None

    def get_response_data(self, response, processing_time):
        if 200 <= response.status_code < 300:
            response_data = "Ommited"
        elif 300 <= response.status_code < 500:
            response_data = getattr(response, "data", None) or getattr(
                response, "text", None
            )
        else:
            response_data = HTTPStatus(response.status_code).phrase
        return {
            "status_code": response.status_code,
            "response_message": HTTPStatus(response.status_code).phrase,
            "response_duration": processing_time,
            "response_data": response_data,
            "response_headers": response.headers
        }

    def clean_auth_headers(self, request):
        """
        Cleans sensitive headers while logging others as is.
        """
        sensitive_headers = {
            "authorization",
            "proxy-authorization",
            "www-authenticate",
            "x-access-token",
            "x-api-key",
            "api-key",
            "cookie",
            "set-cookie",
            "x-amz-security-token",
            "x-csrf-token",
        }

        headers = request.headers
        cleaned_headers = {}

        for key, value in headers.items():
            # Mask sensitive headers
            if key.lower() in sensitive_headers:
                cleaned_headers[key] = "*******"
            else:
                cleaned_headers[key] = value  # Log other headers as is

        return cleaned_headers

    def get_cleaned_payload(self, request):
        if request.content_type == "application/json" and request.body:
            payload = request.body.decode("utf-8")
            if "token" in payload:
                return "**"
            payload_dict = orjson.loads(payload)
            if "password" in payload_dict:
                payload_dict["password"] = "**"
            return payload_dict
        return None

    def get_request_data(self, request):
        data = {
            "request_id": str(uuid.uuid4()),
            "uri": str(request.path),
            "method": request.META["REQUEST_METHOD"],
            "payload": self.cleaned_payload,
            "query_params": request.META.get("QUERY_STRING", ""),
            "content_length": request.headers.get("Content-Length", ""),
            "content_type": request.content_type,
            "remote_host": request.META.get("REMOTE_HOST", ""),
            "remote_ip": request.META.get("REMOTE_ADDR", ""),
            "server": request.META.get("SERVER_NAME", ""),
            "port": request.META.get("SERVER_PORT", ""),
            "headers": self.clean_auth_headers(request),
            "user_agent": request.META.get("HTTP_USER_AGENT", ""),
            "protocol": request.META.get("SERVER_PROTOCOL", ""),
            "referer": request.META.get("HTTP_REFERER", ""),
            "user_id": request.user.id or "Anonymous",
        }
        data.update(self.clean_auth_headers(request))
        return data
