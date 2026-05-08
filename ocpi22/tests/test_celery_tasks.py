import ssl
from unittest.mock import patch, Mock
from urllib.parse import urlparse

import pytest
import requests
import responses
from celery.exceptions import Retry
from requests import RequestException
from responses import matchers

from ocpi22.tasks import (
    send_hubject_request,
    send_hubject_evse_full_load,
    send_ocpi_request,
)
from ocpi22.tests.factories import (
    CredentialsFactory,
)
from ocpiconnector.exceptions import ConnectorTariffNotFoundError


class TestSendHubjectRequest:
    HUBJECT_URL = "https://hubject-api.com/endpoint"
    TIMEOUT = 30

    @pytest.fixture
    def payload_json(self):
        return {"key": "value"}

    @pytest.fixture
    def mock_client(self):
        with patch(
            "integrations.hubject.services.HubjectService.client"
        ) as mock_client:
            mock_client.session = Mock()
            yield mock_client

    @responses.activate
    @pytest.mark.django_db
    def test_send_hubject_request_successfully(self, payload_json, hubject_credentials):
        responses.add(
            responses.PUT,
            TestSendHubjectRequest.HUBJECT_URL,
            json={"Result": True, "StatusCode": {"Code": "2000"}},
            status=200,
            match=[matchers.json_params_matcher(payload_json)],
        )
        with patch.object(send_hubject_request, "app") as mock_app:
            mock_app.conf.task_always_eager = False
            result = send_hubject_request(
                payload_json,
                TestSendHubjectRequest.HUBJECT_URL,
                TestSendHubjectRequest.TIMEOUT,
                hubject_credentials.id,
                "put",
            )
            assert result is None

    @responses.activate
    @pytest.mark.django_db
    def test_send_hubject_request_unsupported_method(
        self, payload_json, caplog, hubject_credentials
    ):
        responses.add(
            url=TestSendHubjectRequest.HUBJECT_URL,
            method="INVALID_METHOD",
            json={"success": False, "error": "hubject error"},
            status=405,
            match=[matchers.json_params_matcher(payload_json)],
        )

        with patch.object(send_hubject_request, "app") as mock_app:
            mock_app.conf.task_always_eager = False
            with pytest.raises(
                NotImplementedError,
                match="Method invalid_method is not supported for send_hubject_request",
            ):
                send_hubject_request(
                    payload_json,
                    TestSendHubjectRequest.HUBJECT_URL,
                    TestSendHubjectRequest.TIMEOUT,
                    hubject_credentials.id,
                    "invalid_method",
                )

    @responses.activate
    @pytest.mark.django_db
    def test_send_hubject_request_eager_mode_does_not_retry(
        self, payload_json, monkeypatch, hubject_credentials
    ):
        responses.add(
            responses.POST,
            TestSendHubjectRequest.HUBJECT_URL,
            json={"success": False, "error": "hubject error"},
            status=500,
            match=[matchers.json_params_matcher(payload_json)],
        )

        with (
            patch("celery.app.task.Task.request") as mock_request,
            patch.object(send_hubject_request, "app") as mock_app,
        ):
            mock_app.conf.task_always_eager = True
            send_hubject_request(
                payload_json,
                TestSendHubjectRequest.HUBJECT_URL,
                TestSendHubjectRequest.TIMEOUT,
                hubject_credentials.id,
                "post",
            )

            mock_request.retry.assert_not_called()

    @responses.activate
    @pytest.mark.django_db
    @pytest.mark.parametrize("status_code", [500, 502, 503])
    def test_send_hubject_request_when_status_code_gte_500_retry_sending_request(
        self, payload_json, status_code, hubject_credentials
    ):
        responses.add(
            responses.POST,
            TestSendHubjectRequest.HUBJECT_URL,
            json={"success": False, "error": "hubject error"},
            status=status_code,
            match=[matchers.json_params_matcher(payload_json)],
        )

        mock_retry = Mock(side_effect=Retry("Server error retry"))

        with (
            patch.object(send_hubject_request, "retry", mock_retry),
            patch.object(send_hubject_request, "app") as mock_app,
            patch("ocpi22.tasks.send_hubject_request.request.retries", 0),
        ):
            mock_app.conf.task_always_eager = False
            with pytest.raises(Retry):
                send_hubject_request(
                    payload_json,
                    TestSendHubjectRequest.HUBJECT_URL,
                    TestSendHubjectRequest.TIMEOUT,
                    hubject_credentials.id,
                    "post",
                )
            mock_retry.assert_called_once()
            call_args = mock_retry.call_args
            assert "Server Error" in str(call_args.kwargs["exc"])

    @responses.activate
    @pytest.mark.django_db
    @pytest.mark.parametrize("status_code", [300, 400])
    def test_send_hubject_request_when_status_code_lt_500_does_not_retry_sending_request(
        self, payload_json, status_code, hubject_credentials
    ):
        responses.add(
            responses.POST,
            TestSendHubjectRequest.HUBJECT_URL,
            json={"success": False, "error": "hubject error"},
            status=status_code,
            match=[matchers.json_params_matcher(payload_json)],
        )

        mock_retry = Mock(side_effect=Retry("Server error retry"))

        with (
            patch.object(send_hubject_request, "retry", mock_retry),
            patch.object(send_hubject_request, "app") as mock_app,
            patch("ocpi22.tasks.send_hubject_request.request.retries", 0),
        ):
            mock_app.conf.task_always_eager = False
            send_hubject_request(
                payload_json,
                TestSendHubjectRequest.HUBJECT_URL,
                TestSendHubjectRequest.TIMEOUT,
                hubject_credentials.id,
                "post",
            )

            mock_retry.assert_not_called()

    @pytest.mark.django_db
    def test_send_hubject_request_when_raised_request_exception_retry_sending_request(
        self, payload_json, hubject_credentials
    ):
        mock_retry = Mock(side_effect=Retry("Server error retry"))

        with (
            patch(
                "integrations.hubject.services.HubjectService._get_request",
                side_effect=RequestException("Request failed"),
            ),
            patch.object(send_hubject_request, "retry", mock_retry),
            patch("ocpi22.tasks.send_hubject_request.request.retries", 0),
        ):
            with pytest.raises(Retry):
                send_hubject_request(
                    payload_json,
                    TestSendHubjectRequest.HUBJECT_URL,
                    TestSendHubjectRequest.TIMEOUT,
                    hubject_credentials.id,
                    "post",
                )

                mock_retry.assert_called()


class TestSendHubjectEvseFullLoad:
    def test_send_hubject_evse_full_load_return_none_for_empty_payload(self):
        with patch(
            "integrations.hubject.services.HubjectService.get_evse_full_load_payload",
            return_value=None,
        ):
            result = send_hubject_evse_full_load()
            assert result is None

    def test_send_hubject_evse_full_load_return_none_when_evses_do_not_have_connectors(
        self,
    ):
        with patch(
            "integrations.hubject.services.HubjectService.get_evse_full_load_payload"
        ) as mock_get_payload:
            mock_get_payload.side_effect = ConnectorTariffNotFoundError()
            result = send_hubject_evse_full_load()
            assert result is None


class TestSendOCPIRequest:
    @pytest.fixture
    def base_request_params(self):
        return {
            "token_base64": "dG9rZW4=",
            "to_country_code": "NL",
            "to_party_id": "ABC",
            "from_country_code": "NL",
            "from_party_id": "XYZ",
        }

    @pytest.fixture
    def test_url(self):
        return (
            "https://ocpi-partner.example.com/ocpi/cpo/2.2.1/tariffs/NL/ABC/tariff-123"
        )

    @pytest.fixture
    def payload(self):
        return {"id": "12345", "value": "test_value"}

    @responses.activate
    @pytest.mark.django_db
    def test_successful_request_with_valid_ocpi_response(
        self, test_url, payload, base_request_params
    ):
        credentials = CredentialsFactory()
        responses.add(
            responses.POST,
            test_url,
            json={
                "status_code": 1000,
                "status_message": "Success",
                "timestamp": "2024-01-01T00:00:00Z",
                "data": {"result": "ok"},
            },
            status=200,
            match=[matchers.json_params_matcher(payload)],
        )

        with patch("celery.app.task.Task.request") as mock_request:
            mock_request.is_eager = True
            result = send_ocpi_request(
                data=payload,
                url=test_url,
                credentials_id=credentials.id,
                method="post",
                **base_request_params,
            )

            assert result is not None
            assert result.status_code == 200

    @responses.activate
    @pytest.mark.django_db
    @pytest.mark.parametrize("method", ["post", "put", "patch", "get", "delete"])
    def test_supports_different_http_methods(
        self, test_url, payload, base_request_params, method
    ):
        credentials = CredentialsFactory()
        responses.add(
            getattr(responses, method.upper()),
            test_url,
            json={
                "status_code": 1000,
                "status_message": "Success",
                "timestamp": "2024-01-01T00:00:00Z",
                "data": None,
            },
            status=200,
        )

        with patch("celery.app.task.Task.request") as mock_request:
            mock_request.is_eager = True
            result = send_ocpi_request(
                data=payload,
                url=test_url,
                credentials_id=credentials.id,
                method=method,
                **base_request_params,
            )

            assert result is not None
            assert result.status_code == 200

    @pytest.mark.django_db
    def test_unsupported_http_method_raises_not_implemented(
        self, test_url, payload, base_request_params
    ):
        credentials = CredentialsFactory()

        with pytest.raises(
            NotImplementedError, match="Method invalid_method is not supported"
        ):
            send_ocpi_request(
                data=payload,
                url=test_url,
                credentials_id=credentials.id,
                method="invalid_method",
                **base_request_params,
            )

    @responses.activate
    @pytest.mark.django_db
    def test_timeout_returns_none_and_logs_error(
        self, test_url, payload, base_request_params, caplog
    ):
        credentials = CredentialsFactory()
        responses.add(
            responses.POST,
            test_url,
            body=requests.Timeout("Connection timeout"),
        )

        result = send_ocpi_request(
            data=payload,
            url=test_url,
            credentials_id=credentials.id,
            method="post",
            **base_request_params,
        )

        assert result is None
        assert (
            f"{urlparse(test_url).hostname} timed out after 3s, not retrying"
            in caplog.text
        )

    @responses.activate
    @pytest.mark.django_db
    def test_request_exception_returns_none_and_logs_warning(
        self, test_url, payload, base_request_params, caplog
    ):
        credentials = CredentialsFactory()
        responses.add(
            responses.POST,
            test_url,
            body=RequestException("Connection error"),
        )

        result = send_ocpi_request(
            data=payload,
            url=test_url,
            credentials_id=credentials.id,
            method="post",
            **base_request_params,
        )

        assert result is None
        assert (
            f"{urlparse(test_url).hostname} non-retryable requests error" in caplog.text
        )

    @pytest.mark.django_db
    def test_ssl_error_returns_none_and_logs_exception(
        self, test_url, payload, base_request_params, caplog
    ):
        credentials = CredentialsFactory()

        with patch(
            "ocpi22.tasks.get_certificate_loaded_request",
            side_effect=ssl.SSLError("Certificate verification failed"),
        ):
            result = send_ocpi_request(
                data=payload,
                url=test_url,
                credentials_id=credentials.id,
                method="post",
                **base_request_params,
            )

            assert result is None
            assert f"SSL error while creating session for {test_url}" in caplog.text

    @responses.activate
    @pytest.mark.django_db
    @pytest.mark.parametrize("status_code", [301, 302, 400, 401, 403, 404, 422])
    def test_3xx_and_4xx_status_codes_return_none_without_retry(
        self, test_url, payload, base_request_params, status_code, caplog
    ):
        credentials = CredentialsFactory()
        responses.add(
            responses.POST,
            test_url,
            json={"error": "Client or redirect error"},
            status=status_code,
        )

        mock_retry = Mock(side_effect=Retry("Should not retry"))

        with patch.object(send_ocpi_request, "retry", mock_retry):
            result = send_ocpi_request(
                data=payload,
                url=test_url,
                credentials_id=credentials.id,
                method="post",
                **base_request_params,
            )

            assert result is None
            assert (
                f"{urlparse(test_url).hostname} responded with {status_code}, not retrying"
                in caplog.text
            )
            mock_retry.assert_not_called()

    @responses.activate
    @pytest.mark.django_db
    @pytest.mark.parametrize("status_code", [500, 502, 503, 504])
    def test_5xx_status_codes_retry_in_non_eager_mode(
        self, test_url, payload, base_request_params, status_code
    ):
        credentials = CredentialsFactory()
        responses.add(
            responses.POST,
            test_url,
            json={"error": "Server error"},
            status=status_code,
        )

        mock_retry = Mock(side_effect=Retry("Retrying server error"))

        with (
            patch.object(send_ocpi_request, "retry", mock_retry),
            patch("celery.app.task.Task.request") as mock_request,
            patch("ocpi22.tasks.send_ocpi_request.request.retries", 0),
        ):
            mock_request.is_eager = False
            mock_request.called_directly = False
            with pytest.raises(Retry):
                send_ocpi_request(
                    data=payload,
                    url=test_url,
                    credentials_id=credentials.id,
                    method="post",
                    **base_request_params,
                )

            mock_retry.assert_called_once()
            call_args = mock_retry.call_args
            assert "Server Error" in str(call_args.kwargs["exc"])
            assert str(status_code) in str(call_args.kwargs["exc"])

    @responses.activate
    @pytest.mark.django_db
    @pytest.mark.parametrize("status_code", [500, 502, 503, 504])
    def test_5xx_status_codes_return_none_in_eager_mode(
        self, test_url, payload, base_request_params, status_code, caplog
    ):
        credentials = CredentialsFactory()
        responses.add(
            responses.POST,
            test_url,
            json={"error": "Server error"},
            status=status_code,
        )

        mock_retry = Mock(side_effect=Retry("Should not retry"))

        with (
            patch.object(send_ocpi_request, "retry", mock_retry),
            patch("celery.app.task.Task.request") as mock_request,
        ):
            mock_request.is_eager = True
            result = send_ocpi_request(
                data=payload,
                url=test_url,
                credentials_id=credentials.id,
                method="post",
                **base_request_params,
            )

            assert result is None
            assert (
                f"{urlparse(test_url).hostname} responded with {status_code}, not retrying"
                in caplog.text
            )
            mock_retry.assert_not_called()

    @responses.activate
    @pytest.mark.django_db
    def test_json_decode_error_returns_none_and_logs_error(
        self, test_url, payload, base_request_params, caplog
    ):
        credentials = CredentialsFactory()
        responses.add(
            responses.POST,
            test_url,
            body="Invalid JSON response",
            status=200,
        )

        result = send_ocpi_request(
            data=payload,
            url=test_url,
            credentials_id=credentials.id,
            method="post",
            **base_request_params,
        )

        assert result is None
        assert (
            f"{urlparse(test_url).hostname} returned non-JSON response with status 200"
            in caplog.text
        )

    @responses.activate
    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "ocpi_status_code,status_message",
        [
            (2000, "Generic client error"),
            (2001, "Invalid or missing parameters"),
            (2002, "Not enough information"),
            (3000, "Generic server error"),
        ],
    )
    def test_ocpi_error_codes_gte_2000_return_none_and_log_error(
        self,
        test_url,
        payload,
        base_request_params,
        ocpi_status_code,
        status_message,
        caplog,
    ):
        credentials = CredentialsFactory()
        responses.add(
            responses.POST,
            test_url,
            json={
                "status_code": ocpi_status_code,
                "status_message": status_message,
                "timestamp": "2024-01-01T00:00:00Z",
                "data": None,
            },
            status=200,
            match=[matchers.json_params_matcher(payload)],
        )

        result = send_ocpi_request(
            data=payload,
            url=test_url,
            credentials_id=credentials.id,
            method="post",
            **base_request_params,
        )

        assert result is None
        assert (
            f"{urlparse(test_url).hostname} responded with OCPI error code {ocpi_status_code}: {status_message}, not retrying"
            in caplog.text
        )

    @responses.activate
    @pytest.mark.django_db
    @pytest.mark.parametrize("ocpi_status_code", [1000, 1001, 1002, 1999])
    def test_ocpi_success_codes_lt_2000_return_response(
        self, test_url, payload, base_request_params, ocpi_status_code, caplog
    ):
        credentials = CredentialsFactory()
        responses.add(
            responses.POST,
            test_url,
            json={
                "status_code": ocpi_status_code,
                "status_message": "Success",
                "timestamp": "2024-01-01T00:00:00Z",
                "data": {"result": "ok"},
            },
            status=200,
            match=[matchers.json_params_matcher(payload)],
        )

        with patch("celery.app.task.Task.request") as mock_request:
            mock_request.is_eager = True
            result = send_ocpi_request(
                data=payload,
                url=test_url,
                credentials_id=credentials.id,
                method="post",
                **base_request_params,
            )

            assert result is not None
            assert result.status_code == 200
            assert (
                f"responded with OCPI error code {ocpi_status_code}" not in caplog.text
            )

    @responses.activate
    @pytest.mark.django_db
    def test_missing_ocpi_status_code_defaults_to_1000(
        self, test_url, payload, base_request_params
    ):
        credentials = CredentialsFactory()
        responses.add(
            responses.POST,
            test_url,
            json={
                "timestamp": "2024-01-01T00:00:00Z",
                "data": {"result": "ok"},
            },
            status=200,
            match=[matchers.json_params_matcher(payload)],
        )

        with patch("celery.app.task.Task.request") as mock_request:
            mock_request.is_eager = True
            result = send_ocpi_request(
                data=payload,
                url=test_url,
                credentials_id=credentials.id,
                method="post",
                **base_request_params,
            )

            assert result is not None
            assert result.status_code == 200

    @responses.activate
    @pytest.mark.django_db
    def test_successful_request_returns_none_in_non_eager_mode(
        self, test_url, payload, base_request_params
    ):
        credentials = CredentialsFactory()
        responses.add(
            responses.POST,
            test_url,
            json={
                "status_code": 1000,
                "status_message": "Success",
                "timestamp": "2024-01-01T00:00:00Z",
                "data": {"result": "ok"},
            },
            status=200,
            match=[matchers.json_params_matcher(payload)],
        )

        with patch("celery.app.task.Task.request") as mock_request:
            mock_request.is_eager = False
            mock_request.called_directly = False
            result = send_ocpi_request(
                data=payload,
                url=test_url,
                credentials_id=credentials.id,
                method="post",
                **base_request_params,
            )

            assert result is None

    @responses.activate
    @pytest.mark.django_db
    def test_successful_request_returns_response_when_called_directly(
        self, test_url, payload, base_request_params
    ):
        """Test direct function calls (like from pull_objects) return response."""
        credentials = CredentialsFactory()
        responses.add(
            responses.POST,
            test_url,
            json={
                "status_code": 1000,
                "status_message": "Success",
                "timestamp": "2024-01-01T00:00:00Z",
                "data": {"result": "ok"},
            },
            status=200,
            match=[matchers.json_params_matcher(payload)],
        )

        with patch("celery.app.task.Task.request") as mock_request:
            mock_request.is_eager = False
            mock_request.called_directly = True
            result = send_ocpi_request(
                data=payload,
                url=test_url,
                credentials_id=credentials.id,
                method="post",
                **base_request_params,
            )

            assert result is not None
            assert result.status_code == 200
