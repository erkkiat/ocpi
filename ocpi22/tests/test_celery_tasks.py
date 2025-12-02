from unittest.mock import patch, Mock

import pytest

import responses
from celery.exceptions import Retry
from requests import RequestException
from responses import matchers

from ocpi22.tasks import (
    send_hubject_request,
    send_hubject_evse_full_load,
    send_ocpi_request,
)
from ocpi22.tests.factories import CredentialsFactory
from ocpiconnector.exceptions import ConnectorTariffNotFoundError


class TestSendHubjectRequest:
    HUBJECT_URL = "https://hubject-api.com/endpoint"

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
    def test_send_hubject_request_successfully(self, payload_json):
        responses.add(
            responses.PUT,
            TestSendHubjectRequest.HUBJECT_URL,
            json={"success": True},
            status=200,
            match=[matchers.json_params_matcher(payload_json)],
        )
        with patch.object(send_hubject_request, "app") as mock_app:
            mock_app.conf.task_always_eager = False
            result = send_hubject_request(
                payload_json, TestSendHubjectRequest.HUBJECT_URL
            )
            assert result is None

    @responses.activate
    def test_send_hubject_request_unsupported_method(self, payload_json, caplog):
        responses.add(
            url=TestSendHubjectRequest.HUBJECT_URL,
            method="INVALID_METHOD",
            json={"success": False, "error": "hubject error"},
            status=405,
            match=[matchers.json_params_matcher(payload_json)],
        )

        with patch.object(send_hubject_request, "app") as mock_app:
            mock_app.conf.task_always_eager = False
            result = send_hubject_request(
                payload_json, TestSendHubjectRequest.HUBJECT_URL, "invalid_method"
            )
            assert result is None
            assert (
                caplog.records[1].message
                == "Got 405 for https://hubject-api.com/endpoint: {'success': False, 'error': 'hubject error'}"
            )

    @responses.activate
    @pytest.mark.django_db
    def test_send_hubject_request_eager_mode_does_not_retry(
        self, payload_json, monkeypatch
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
                payload_json, TestSendHubjectRequest.HUBJECT_URL, "post"
            )

            mock_request.retry.assert_not_called()

    @responses.activate
    @pytest.mark.django_db
    @pytest.mark.parametrize("status_code", [500, 502, 503])
    def test_send_hubject_request_when_status_code_gte_500_retry_sending_request(
        self, payload_json, status_code
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
                    payload_json, TestSendHubjectRequest.HUBJECT_URL, "post"
                )
            mock_retry.assert_called_once()
            call_args = mock_retry.call_args
            assert "Server Error" in str(call_args.kwargs["exc"])

    @responses.activate
    @pytest.mark.django_db
    @pytest.mark.parametrize("status_code", [300, 400])
    def test_send_hubject_request_when_status_code_lt_500_does_not_retry_sending_request(
        self, payload_json, status_code
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
                payload_json, TestSendHubjectRequest.HUBJECT_URL, "post"
            )

            mock_retry.assert_not_called()

    @pytest.mark.django_db
    def test_send_hubject_request_when_raised_request_exception_retry_sending_request(
        self, payload_json
    ):
        mock_retry = Mock(side_effect=Retry("Server error retry"))

        with (
            patch(
                "integrations.hubject.services.HubjectService.client.session.request",
                side_effect=RequestException("Request failed"),
            ),
            patch.object(send_hubject_request, "retry", mock_retry),
            patch("ocpi22.tasks.send_hubject_request.request.retries", 0),
        ):
            with pytest.raises(Retry):
                send_hubject_request(
                    payload_json, TestSendHubjectRequest.HUBJECT_URL, "post"
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


class TestSendOCPIRequestErrorLogging:
    @responses.activate
    @pytest.mark.django_db
    def test_error_logs_when_status_code_gte_2000(self, caplog):
        data = {"id": "12345", "value": "test_value"}
        url = "https://somerandomurl.random.com/resource"
        credentials = CredentialsFactory()
        responses.add(
            responses.POST,
            url,
            json={
                "status_code": 2000,
                "status_message": "OCPI specific error occurred",
                "timestamp": "2024-01-01T00:00:00Z",
                "data": None,
            },
            status=200,
            match=[matchers.json_params_matcher(data)],
        )
        with patch.object(send_ocpi_request, "app") as mock_app:
            mock_app.conf.task_always_eager = False
            send_ocpi_request(
                data=data,
                url=url,
                token_base64="dG9rZW4=",
                to_country_code="NL",
                to_party_id="ABC",
                from_country_code="NL",
                from_party_id="XYZ",
                credentials_id=credentials.id,
                method="post",
            )

            assert (
                f"{url} responded with OCPI error code 2000: OCPI specific error occurred, not retrying"
                in caplog.text
            )

    @responses.activate
    @pytest.mark.django_db
    def test_error_logs_when_status_code_lt_2000(self, caplog):
        data = {"id": "12345", "value": "test_value"}
        url = "https://somerandomurl.random.com/resource"
        credentials = CredentialsFactory()
        responses.add(
            responses.POST,
            url,
            json={
                "status_code": 1000,
                "status_message": "Success",
                "timestamp": "2024-01-01T00:00:00Z",
                "data": None,
            },
            status=200,
            match=[matchers.json_params_matcher(data)],
        )
        with patch.object(send_ocpi_request, "app") as mock_app:
            mock_app.conf.task_always_eager = False
            result = send_ocpi_request(
                data=data,
                url=url,
                token_base64="dG9rZW4=",
                to_country_code="NL",
                to_party_id="ABC",
                from_country_code="NL",
                from_party_id="XYZ",
                credentials_id=credentials.id,
                method="post",
            )

            assert result.status_code == 200
            assert (
                f"{url} responded with OCPI error code 1000: Success" not in caplog.text
            )
