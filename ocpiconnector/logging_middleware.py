import time
import uuid
import logging
from http import HTTPStatus
from typing import Callable, Optional, Dict, Any, List, Mapping

import orjson
import sentry_sdk
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils.deprecation import MiddlewareMixin


class LoggingMiddleware(MiddlewareMixin):
    ignored_paths: List[str] = getattr(
        settings,
        "LOGGING_MIDDLEWARE_IGNORED_PATHS",
        ["/health", "/metrics"],
    )

    sensitive_urls_to_mask_payload: Optional[List[str]] = getattr(
        settings, "LOGGING_MIDDLEWARE_SENSITIVE_URLS", []
    )

    sensitive_headers: set = {
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

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        super().__init__(get_response)
        self.get_response = get_response
        self.logger = logging.getLogger(__name__)

    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        if request.path in self.ignored_paths:
            request._skip_logging = True
            return None
        request._skip_logging = False
        request.start_time = time.time()
        request.request_id = str(uuid.uuid4())
        request.view_name = None
        request._logging_exception = None
        request._cleaned_payload = self._get_cleaned_payload(request)
        return None

    def process_view(
        self,
        request: HttpRequest,
        view_func: Callable,
        view_args: List[Any],
        view_kwargs: Dict[str, Any],
    ) -> Optional[HttpResponse]:
        if not getattr(request, "_skip_logging", False):
            request.view_name = f"{view_func.__module__}.{view_func.__name__}"
        return None

    def process_exception(
        self, request: HttpRequest, exception: Exception
    ) -> Optional[HttpResponse]:
        if getattr(request, "_skip_logging", False):
            return None
        request._logging_exception = exception
        try:
            sentry_sdk.capture_exception(exception)
        except Exception:
            self.logger.exception("Sentry capture failed")
        return None

    def process_response(
        self, request: HttpRequest, response: HttpResponse
    ) -> HttpResponse:
        if getattr(request, "_skip_logging", False):
            return response
        try:
            duration = time.time() - getattr(request, "start_time", time.time())
            extra = {
                **self.get_request_data(request),
                **self.get_response_data(response, duration),
            }
            message = f"{extra['path']} {extra['response_message']}"
            exc = getattr(request, "_logging_exception", None)
            if exc:
                self.logger.exception(message, extra=extra)
            elif response.status_code >= 500:
                self.logger.error(message, extra=extra)
            elif response.status_code >= 400:
                self.logger.warning(message, extra=extra)
            else:
                self.logger.info(message, extra=extra)
        except Exception:
            self.logger.exception("LoggingMiddleware.process_response failed")
        return response

    def get_request_data(self, request: HttpRequest) -> Dict[str, Any]:
        return {
            "request_id": request.request_id,
            "view": request.view_name,
            "path": request.get_full_path(),
            "method": request.method,
            "payload": request._cleaned_payload,
            "content_length": request.headers.get("Content-Length", ""),
            "content_type": request.content_type or "",
            "remote_ip": self._get_client_ip(request),
            "headers": self._clean_headers_dict(request.headers),
            "user_agent": request.META.get("HTTP_USER_AGENT", ""),
            "protocol": request.META.get("SERVER_PROTOCOL", ""),
            "referer": request.META.get("HTTP_REFERER", ""),
            "user_id": self._get_user_id(request),
        }

    def get_response_data(
        self, response: HttpResponse, duration: float
    ) -> Dict[str, Any]:
        status = response.status_code
        if 200 <= status < 300:
            data = "Omitted"
        elif 300 <= status < 500:
            data = self.get_raw_response(response)
        else:
            data = HTTPStatus(status).phrase
        return {
            "status_code": status,
            "response_message": HTTPStatus(status).phrase,
            "response_duration": duration,
            "response_data": data,
            "response_headers": self._clean_headers_dict(
                getattr(response, "headers", {})
            ),
        }

    def _get_cleaned_payload(self, request: HttpRequest) -> Optional[str]:
        raw = self._safe_get_raw_body(request)
        if raw is None:
            return None

        if not self._is_sensitive_path(request.path):
            return raw

        if self._is_json_write(request):
            try:
                parsed = orjson.loads(raw)
                masked = self.mask_sensitive_data(parsed)
                return orjson.dumps(masked).decode("utf-8")
            except Exception:
                return raw

        return None

    def _safe_get_raw_body(self, request: HttpRequest) -> Optional[str]:
        try:
            body_bytes = request.body
        except Exception:
            return None
        if not body_bytes:
            return None
        try:
            return body_bytes.decode("utf-8", errors="ignore")
        except Exception:
            return None

    def _is_sensitive_path(self, path: str) -> bool:
        return any(path.startswith(p) for p in self.sensitive_urls_to_mask_payload)

    def _is_json_write(self, request: HttpRequest) -> bool:
        if request.method not in ("POST", "PUT", "PATCH"):
            return False
        ct = (request.content_type or "").lower()
        return ct.startswith("application/json")

    def get_raw_response(self, response: HttpResponse) -> str:
        try:
            raw = response.content.decode("utf-8", errors="replace")
            return raw
        except Exception:
            return "**binary_or_unreadable_content**"

    def _clean_headers_dict(self, headers: Mapping[str, Any]) -> Dict[str, str]:
        cleaned: Dict[str, str] = {}
        for k, v in dict(headers).items():
            val = str(v)
            cleaned[k] = (
                self.partial_mask(val) if k.lower() in self.sensitive_headers else val
            )
        return cleaned

    def mask_sensitive_data(self, data: Any) -> Any:
        if isinstance(data, dict):
            result: Dict[str, Any] = {}
            for k, v in data.items():
                lk = k.lower()
                if lk in ("password", "secret", "private_key"):
                    result[k] = "**masked**"
                elif lk in (
                    "token",
                    "access_token",
                    "refresh_token",
                    "auth_token",
                    "api_key",
                    "authorization",
                    "bearer",
                    "jwt",
                ):
                    result[k] = self.partial_mask(str(v))
                elif isinstance(v, (dict, list)):
                    result[k] = self.mask_sensitive_data(v)
                else:
                    result[k] = v
            return result
        if isinstance(data, list):
            return [self.mask_sensitive_data(i) for i in data]
        return data

    def partial_mask(self, value: str, show_start: int = 4, show_end: int = 4) -> str:
        return (
            ("*" * len(value))
            if len(value) <= show_start + show_end
            else f"{value[:show_start]}****{value[-show_end:]}"
        )

    def _get_client_ip(self, request: HttpRequest) -> str:
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")

    def _get_user_id(self, request: HttpRequest) -> str:
        try:
            uid = getattr(request.user, "id", None)
            return str(uid) if uid else "Anonymous"
        except Exception:
            return "Anonymous"
