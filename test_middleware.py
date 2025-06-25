import time

import pytest
import orjson
from django.test import RequestFactory
from django.http import HttpResponse
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from middlewares import AllowHealthCheckMiddleware
from ocpiconnector.logging_middleware import LoggingMiddleware

from unittest.mock import Mock, patch, PropertyMock


@pytest.mark.django_db
def test_health_check_middleware_success(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", True)

    request = RequestFactory().get("/health-check/")
    request.META["HTTP_HOST"] = "testserver"

    middleware = AllowHealthCheckMiddleware(lambda req: HttpResponse("Fallback"))
    response = middleware(request)

    assert response.status_code == 200
    assert response.content == b"OK"


@pytest.mark.django_db
def test_health_check_middleware_failure(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", True)

    request = RequestFactory().get("/health-check/")
    request.META["HTTP_HOST"] = "testserver"

    monkeypatch.setattr(AllowHealthCheckMiddleware, "check_health", lambda self: False)
    middleware = AllowHealthCheckMiddleware(lambda req: HttpResponse("Fallback"))
    response = middleware(request)

    assert response.status_code == 500
    assert response.content == b"Service Unhealthy"


class TestLoggingMiddleware:
    @pytest.fixture
    def middleware(self):
        get_response = Mock(return_value=HttpResponse("OK", status=200))
        return LoggingMiddleware(get_response)

    @pytest.fixture
    def request_factory(self):
        return RequestFactory()

    def test_process_request_sets_skip_logging_for_ignored_paths(
        self, middleware, request_factory
    ):
        request = request_factory.get("/health")

        result = middleware.process_request(request)

        assert result is None
        assert request._skip_logging is True

    def test_process_request_initializes_request_attributes_for_tracked_paths(
        self, middleware, request_factory
    ):
        request = request_factory.get("/api/locations")

        with patch("time.time", return_value=1234567890.123):
            with patch("uuid.uuid4", return_value="test-uuid"):
                result = middleware.process_request(request)

        assert result is None
        assert request._skip_logging is False
        assert request.start_time == 1234567890.123
        assert request.request_id == "test-uuid"
        assert request.view_name is None
        assert request._logging_exception is None
        assert hasattr(request, "_cleaned_payload")

    def test_process_view_sets_view_name_when_not_skipping_logging(
        self, middleware, request_factory
    ):
        request = request_factory.get("/api/locations")
        request._skip_logging = False
        view_func = Mock()
        view_func.__module__ = "test.module"
        view_func.__name__ = "test_view"

        result = middleware.process_view(request, view_func, [], {})

        assert result is None
        assert request.view_name == "test.module.test_view"

    def test_process_view_skips_when_logging_disabled(
        self, middleware, request_factory
    ):
        request = request_factory.get("/health")
        request._skip_logging = True
        view_func = Mock()

        result = middleware.process_view(request, view_func, [], {})

        assert result is None
        assert not hasattr(request, "view_name")

    def test_process_exception_sets_exception_and_captures_sentry(
        self, middleware, request_factory
    ):
        request = request_factory.get("/api/locations")
        request._skip_logging = False
        exception = ValueError("Test error")

        with patch("sentry_sdk.capture_exception") as mock_sentry:
            result = middleware.process_exception(request, exception)

        assert result is None
        assert request._logging_exception == exception
        mock_sentry.assert_called_once_with(exception)

    def test_process_exception_handles_sentry_failure_gracefully(
        self, middleware, request_factory
    ):
        request = request_factory.get("/api/locations")
        request._skip_logging = False
        exception = ValueError("Test error")

        with patch(
            "sentry_sdk.capture_exception", side_effect=Exception("Sentry error")
        ):
            with patch.object(middleware.logger, "exception") as mock_exception:
                result = middleware.process_exception(request, exception)

        assert result is None
        assert request._logging_exception == exception
        mock_exception.assert_called_once_with("Sentry capture failed")

    def test_process_exception_skips_when_logging_disabled(
        self, middleware, request_factory
    ):
        request = request_factory.get("/health")
        request._skip_logging = True
        exception = ValueError("Test error")

        with patch("sentry_sdk.capture_exception") as mock_sentry:
            result = middleware.process_exception(request, exception)

        assert result is None
        mock_sentry.assert_not_called()

    def test_process_response_skips_when_logging_disabled(
        self, middleware, request_factory
    ):
        request = request_factory.get("/health")
        request._skip_logging = True
        response = HttpResponse("OK", status=200)

        with patch.object(middleware.logger, "info") as mock_info:
            with patch.object(middleware.logger, "warning") as mock_warning:
                with patch.object(middleware.logger, "error") as mock_error:
                    with patch.object(middleware.logger, "exception") as mock_exception:
                        result = middleware.process_response(request, response)

        assert result == response
        mock_info.assert_not_called()
        mock_warning.assert_not_called()
        mock_error.assert_not_called()
        mock_exception.assert_not_called()

    def test_process_response_logs_info_for_success_status(
        self, middleware, request_factory
    ):
        request = request_factory.get("/api/locations")
        request._skip_logging = False
        request.start_time = time.time() - 0.5
        request.request_id = "test-id"
        request.view_name = "test.view"
        request._cleaned_payload = None
        response = HttpResponse("OK", status=200)

        with patch.object(middleware.logger, "info") as mock_info:
            result = middleware.process_response(request, response)

        assert result == response
        mock_info.assert_called_once()
        call_args = mock_info.call_args
        assert "/api/locations OK" in call_args[0][0]

    def test_process_response_logs_warning_for_client_error_status(
        self, middleware, request_factory
    ):
        request = request_factory.get("/api/locations")
        request._skip_logging = False
        request.start_time = time.time() - 0.5
        request.request_id = "test-id"
        request.view_name = "test.view"
        request._cleaned_payload = None
        response = HttpResponse("Not Found", status=404)

        with patch.object(middleware.logger, "warning") as mock_warning:
            result = middleware.process_response(request, response)

        assert result == response
        mock_warning.assert_called_once()
        call_args = mock_warning.call_args
        assert "/api/locations Not Found" in call_args[0][0]

    def test_process_response_logs_error_for_server_error_status(
        self, middleware, request_factory
    ):
        request = request_factory.get("/api/locations")
        request._skip_logging = False
        request.start_time = time.time() - 0.5
        request.request_id = "test-id"
        request.view_name = "test.view"
        request._cleaned_payload = None
        response = HttpResponse("Internal Server Error", status=500)

        with patch.object(middleware.logger, "error") as mock_error:
            result = middleware.process_response(request, response)

        assert result == response
        mock_error.assert_called_once()
        call_args = mock_error.call_args
        assert "/api/locations Internal Server Error" in call_args[0][0]

    def test_process_response_logs_exception_when_exception_occurred(
        self, middleware, request_factory
    ):
        request = request_factory.get("/api/locations")
        request._skip_logging = False
        request.start_time = time.time() - 0.5
        request.request_id = "test-id"
        request.view_name = "test.view"
        request.cleaned_payload = None
        request._logging_exception = ValueError("Test error")
        response = HttpResponse("OK", status=200)

        with patch.object(middleware.logger, "exception") as mock_exception:
            result = middleware.process_response(request, response)

        assert result == response
        mock_exception.assert_called_once()

    def test_process_response_handles_logging_exception_gracefully(
        self, middleware, request_factory
    ):
        request = request_factory.get("/api/locations")
        request._skip_logging = False
        request.start_time = time.time() - 0.5
        request.request_id = "test-id"
        request.view_name = "test.view"
        request.cleaned_payload = None
        response = HttpResponse("OK", status=200)

        with patch.object(
            middleware, "get_request_data", side_effect=Exception("Logging error")
        ):
            with patch.object(middleware.logger, "exception") as mock_exception:
                result = middleware.process_response(request, response)

        assert result == response
        mock_exception.assert_called_with("LoggingMiddleware.process_response failed")

    def test_get_request_data_returns_complete_data_structure(
        self, middleware, request_factory
    ):
        request = request_factory.post(
            "/api/locations", data={"test": "data"}, content_type="application/json"
        )
        request.request_id = "test-id"
        request.view_name = "test.view"
        request._cleaned_payload = '{"test": "data"}'
        request.user = AnonymousUser()
        data = middleware.get_request_data(request)

        assert data["request_id"] == "test-id"
        assert data["view"] == "test.view"
        assert data["path"] == "/api/locations"
        assert data["method"] == "POST"
        assert data["payload"] == '{"test": "data"}'
        assert data["user_id"] == "Anonymous"
        assert "headers" in data
        assert "remote_ip" in data

    def test_get_response_data_omits_data_for_success_responses(self, middleware):
        response = HttpResponse("Success response", status=200)

        data = middleware.get_response_data(response, 0.5)

        assert data["status_code"] == 200
        assert data["response_message"] == "OK"
        assert data["response_duration"] == 0.5
        assert data["response_data"] == "Omitted"

    def test_get_response_data_includes_data_for_redirect_responses(self, middleware):
        response = HttpResponse("Redirect response", status=302)

        data = middleware.get_response_data(response, 0.5)

        assert data["status_code"] == 302
        assert data["response_message"] == "Found"
        assert data["response_duration"] == 0.5
        assert "Redirect response" in data["response_data"]

    def test_get_response_data_includes_phrase_for_server_error_responses(
        self, middleware
    ):
        response = HttpResponse("Server error", status=500)

        data = middleware.get_response_data(response, 0.5)

        assert data["status_code"] == 500
        assert data["response_message"] == "Internal Server Error"
        assert data["response_duration"] == 0.5
        assert data["response_data"] == "Internal Server Error"

    @pytest.mark.parametrize("http_method", ["POST", "PUT", "PATCH"])
    def test_get_cleaned_payload_masks_sensitive_url_json_content(
        self, middleware, request_factory, http_method
    ):
        json_data = {"password": "secret123", "username": "user"}
        request_method = getattr(request_factory, http_method.lower())
        request = request_method(
            "/api/token/", data=orjson.dumps(json_data), content_type="application/json"
        )

        result = middleware._get_cleaned_payload(request)

        parsed = orjson.loads(result)
        assert parsed["password"] == "**masked**"
        assert parsed["username"] == "user"

    @pytest.mark.parametrize("http_method", ["POST", "PUT", "PATCH"])
    def test_get_cleaned_payload_returns_none_for_sensitive_url_non_json(
        self, middleware, request_factory, http_method
    ):
        request_method = getattr(request_factory, http_method.lower())
        request = request_method(
            "/api/token/",
            data="username=user&password=secret",
            content_type="application/x-www-form-urlencoded",
        )

        result = middleware._get_cleaned_payload(request)

        assert result is None

    @pytest.mark.parametrize("http_method", ["POST", "PUT", "PATCH"])
    def test_get_cleaned_payload_returns_raw_for_non_sensitive_urls(
        self, middleware, request_factory, http_method
    ):
        json_data = {"data": "value"}
        request_method = getattr(request_factory, http_method.lower())
        request = request_method(
            "/api/locations/",
            data=orjson.dumps(json_data),
            content_type="application/json",
        )

        result = middleware._get_cleaned_payload(request)

        assert result == '{"data":"value"}'

    def test_get_cleaned_response_handles_binary_content(self, middleware):
        binary_data = b"\xff\xfe\xfa\xfb\x80"
        response = HttpResponse(binary_data, content_type="application/octet-stream")
        cleaned = middleware.get_raw_response(response)
        expected = binary_data.decode("utf-8", errors="replace")
        assert cleaned == expected

    def test_clean_headers_dict_masks_sensitive_headers(self, middleware):
        headers = {
            "Authorization": "Bearer token123456789",
            "Content-Type": "application/json",
            "X-API-Key": "apikey123456789",
        }

        result = middleware._clean_headers_dict(headers)

        assert result["Authorization"] == "Bear****6789"
        assert result["Content-Type"] == "application/json"
        assert result["X-API-Key"] == "apik****6789"

    def test_mask_sensitive_data_handles_nested_dictionaries(self, middleware):
        data = {
            "user": {
                "password": "secret123",
                "token": "access_token_12345",
                "email": "user@example.com",
            },
            "api_key": "key_98765",
        }

        result = middleware.mask_sensitive_data(data)

        assert result["user"]["password"] == "**masked**"
        assert result["user"]["token"] == "acce****2345"
        assert result["user"]["email"] == "user@example.com"
        assert result["api_key"] == "key_****8765"

    def test_mask_sensitive_data_handles_lists(self, middleware):
        data = [{"password": "secret1"}, {"token": "token123456"}, "plain_string"]

        result = middleware.mask_sensitive_data(data)

        assert result[0]["password"] == "**masked**"
        assert result[1]["token"] == "toke****3456"
        assert result[2] == "plain_string"

    def test_partial_mask_handles_short_values(self, middleware):
        result = middleware.partial_mask("abc")

        assert result == "***"

    def test_partial_mask_handles_normal_values(self, middleware):
        result = middleware.partial_mask("1234567890abcdef")

        assert result == "1234****cdef"

    def test_partial_mask_respects_custom_show_parameters(self, middleware):
        result = middleware.partial_mask("1234567890abcdef", show_start=2, show_end=2)

        assert result == "12****ef"

    def test_get_client_ip_extracts_from_x_forwarded_for(
        self, middleware, request_factory
    ):
        request = request_factory.get("/api/locations/")
        request.META["HTTP_X_FORWARDED_FOR"] = "192.168.1.1, 10.0.0.1"

        result = middleware._get_client_ip(request)

        assert result == "192.168.1.1"

    def test_get_client_ip_falls_back_to_remote_addr(self, middleware, request_factory):
        request = request_factory.get("/api/locations/")
        request.META["REMOTE_ADDR"] = "192.168.1.1"

        result = middleware._get_client_ip(request)

        assert result == "192.168.1.1"

    def test_get_client_ip_returns_empty_when_no_ip_available(
        self, middleware, request_factory
    ):
        request = request_factory.get("/api/locations/")
        # Clear the default REMOTE_ADDR that Django RequestFactory sets
        if "REMOTE_ADDR" in request.META:
            del request.META["REMOTE_ADDR"]

        result = middleware._get_client_ip(request)

        assert result == ""

    def test_get_user_id_returns_user_id_for_authenticated_user(
        self, middleware, request_factory
    ):
        request = request_factory.get("/api/locations/")
        user = Mock()
        user.id = 123
        request.user = user

        result = middleware._get_user_id(request)

        assert result == "123"

    def test_get_user_id_returns_anonymous_for_no_user_id(
        self, middleware, request_factory
    ):
        request = request_factory.get("/api/locations/")
        user = Mock()
        user.id = None
        request.user = user

        result = middleware._get_user_id(request)

        assert result == "Anonymous"

    def test_get_user_id_handles_exception_gracefully(
        self, middleware, request_factory
    ):
        request = request_factory.get("/api/locations/")
        request.user = Mock()
        del request.user.id  # Simulate attribute error

        result = middleware._get_user_id(request)

        assert result == "Anonymous"

    @pytest.mark.parametrize("http_method", ["POST", "PUT", "PATCH"])
    def test_malformed_json_in_sensitive_url_returns_raw_content(
        self, middleware, request_factory, http_method
    ):
        malformed_json = '{"invalid": json content'
        request_method = getattr(request_factory, http_method.lower())
        request = request_method(
            "/api/token/", data=malformed_json, content_type="application/json"
        )

        result = middleware._get_cleaned_payload(request)

        assert result == malformed_json

    @pytest.mark.parametrize("http_method", ["POST", "PUT", "PATCH"])
    def test_decode_error_in_request_body_returns_none(
        self, middleware, request_factory, http_method
    ):
        request_method = getattr(request_factory, http_method.lower())
        request = request_method("/api/locations/")

        with patch.object(
            type(request), "body", new_callable=PropertyMock
        ) as mock_body:
            mock_body.side_effect = UnicodeDecodeError("utf-8", b"", 0, 1, "")
            result = middleware._get_cleaned_payload(request)

        assert result is None

    def test_get_cleaned_payload_handles_orjson_decode_error_for_sensitive_urls(
        self, middleware, request_factory
    ):
        malformed_json = '{"invalid": json content'
        request = request_factory.post(
            "/api/token/", data=malformed_json, content_type="application/json"
        )

        result = middleware._get_cleaned_payload(request)

        assert result == malformed_json

    def test_get_cleaned_payload_uses_orjson_for_masking_sensitive_data(
        self, middleware, request_factory
    ):
        complex_data = {
            "password": "secret123",
            "nested": {"api_key": "key12345", "safe_data": "value"},
            "list": [{"token": "token123"}],
        }
        request = request_factory.post(
            "/api/token/",
            data=orjson.dumps(complex_data),
            content_type="application/json",
        )

        result = middleware._get_cleaned_payload(request)

        parsed = orjson.loads(result)
        assert parsed["password"] == "**masked**"
        # The actual middleware masks with ********** for strings 8 chars or less
        assert (
            len(parsed["nested"]["api_key"]) == 8 and "*" in parsed["nested"]["api_key"]
        )
        assert parsed["nested"]["safe_data"] == "value"
        assert (
            len(parsed["list"][0]["token"]) == 8 and "*" in parsed["list"][0]["token"]
        )

    def test_get_cleaned_payload_returns_none_for_body_decode_exception(
        self, middleware, request_factory
    ):
        request = request_factory.post("/api/locations/")

        with patch.object(
            type(request), "body", new_callable=PropertyMock
        ) as mock_body:
            mock_body.side_effect = Exception("Read error")
            result = middleware._get_cleaned_payload(request)

        assert result is None

    def test_get_cleaned_payload_handles_empty_body_gracefully(
        self, middleware, request_factory
    ):
        request = request_factory.post(
            "/api/locations/", data="", content_type="application/json"
        )

        result = middleware._get_cleaned_payload(request)

        assert result is None

    def test_get_cleaned_payload_handles_none_content_type_for_sensitive_urls(
        self, middleware, request_factory
    ):
        request = request_factory.post("/api/token/")
        request._body = b"some data"

        result = middleware._get_cleaned_payload(request)

        assert result is None

    def test_get_cleaned_payload_checks_content_type_starts_with_application_json(
        self, middleware, request_factory
    ):
        json_data = {"password": "secret123"}
        request = request_factory.post(
            "/api/token/",
            data=orjson.dumps(json_data),
            content_type="application/json; charset=utf-8",
        )

        result = middleware._get_cleaned_payload(request)

        parsed = orjson.loads(result)
        assert parsed["password"] == "**masked**"

    def test_get_cleaned_payload_ignores_get_requests_for_sensitive_url_masking(
        self, middleware, request_factory
    ):
        request = request_factory.get("/api/token/", data={"password": "secret123"})

        result = middleware._get_cleaned_payload(request)
        assert result is None

    @pytest.mark.parametrize(
        "test_path",
        [
            "/api-auth/login/",
            "/accounts/login/",
            "/accounts/logout/",
            "/accounts/password_change/",
            "/accounts/password_reset/",
            "/admin/login/",
            "/admin/logout/",
            "/api/token/",
            "/api/token/refresh/",
            "/api/token/verify/",
        ],
    )
    def test_get_cleaned_payload_masks_data_for_configured_sensitive_paths(
        self, middleware, request_factory, test_path
    ):
        json_data = {"password": "secret123", "username": "user"}
        request = request_factory.post(
            test_path, data=orjson.dumps(json_data), content_type="application/json"
        )

        result = middleware._get_cleaned_payload(request)

        parsed = orjson.loads(result)
        assert parsed["password"] == "**masked**"
        assert parsed["username"] == "user"

    @pytest.mark.parametrize(
        "test_path",
        [
            "/api-auth/login/user",
            "/accounts/login/redirect",
            "/accounts/logout/success",
            "/accounts/password_change/done",
            "/accounts/password_reset/confirm",
            "/admin/login/staff",
            "/admin/logout/redirect",
            "/api/token/exchange",
            "/api/token/refresh/new",
            "/api/token/verify/check",
        ],
    )
    def test_get_cleaned_payload_masks_data_for_paths_starting_with_configured_sensitive_urls(
        self, middleware, request_factory, test_path
    ):
        json_data = {"password": "secret123", "api_key": "key12345"}
        request = request_factory.post(
            test_path, data=orjson.dumps(json_data), content_type="application/json"
        )

        result = middleware._get_cleaned_payload(request)

        parsed = orjson.loads(result)
        assert parsed["password"] == "**masked**"
        assert "****" in parsed["api_key"]

    @pytest.mark.parametrize(
        "test_path",
        [
            "/api/locations/",
            "/api/sessions/",
            "/api/cdrs/",
            "/health/",
            "/metrics/",
            "/docs/",
            "/api/",
            "/portal/",
            "/admin/",
        ],
    )
    def test_get_cleaned_payload_returns_raw_data_for_non_sensitive_paths(
        self, middleware, request_factory, test_path
    ):
        json_data = {"password": "secret123", "username": "user"}
        request = request_factory.post(
            test_path, data=orjson.dumps(json_data), content_type="application/json"
        )

        result = middleware._get_cleaned_payload(request)

        assert result == '{"password":"secret123","username":"user"}'
