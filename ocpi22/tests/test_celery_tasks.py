from unittest.mock import patch, Mock

import pytest

import responses
from celery.exceptions import Retry
from requests import RequestException
from responses import matchers

from ocpi22.tasks import send_hubject_request


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
