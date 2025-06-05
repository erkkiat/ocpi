from unittest.mock import patch, Mock

import pytest

import responses
from celery.exceptions import Retry
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

        result = send_hubject_request.delay(
            payload_json, TestSendHubjectRequest.HUBJECT_URL
        )
        assert result.get() == {"success": True}

    @responses.activate
    @pytest.mark.django_db
    @pytest.mark.parametrize("env", ["staging", "development"])
    def test_send_hubject_request_when_status_code_gte_300_retry_sending_request(
        self, monkeypatch, payload_json, env
    ):
        monkeypatch.setenv("ENV", env)

        responses.add(
            responses.POST,
            TestSendHubjectRequest.HUBJECT_URL,
            json={"success": False, "error": "Bad Request"},
            status=400,
            match=[matchers.json_params_matcher(payload_json)],
        )

        with patch("ocpi22.tasks.send_hubject_request.retry") as mock_retry:
            mock_retry.side_effect = Retry()

            with pytest.raises(Retry):
                send_hubject_request.delay(
                    payload_json, TestSendHubjectRequest.HUBJECT_URL, "post"
                )

            mock_retry.assert_called_once()

    @responses.activate
    @pytest.mark.django_db
    @pytest.mark.parametrize("status_code", [500, 502, 503])
    def test_send_hubject_request_when_status_code_gte_500_retry_sending_request(
        self, monkeypatch, payload_json, status_code
    ):
        monkeypatch.setenv("ENV", "production")

        responses.add(
            responses.POST,
            TestSendHubjectRequest.HUBJECT_URL,
            json={"success": False, "error": "hubject error"},
            status=500,
            match=[matchers.json_params_matcher(payload_json)],
        )

        with patch("ocpi22.tasks.send_hubject_request.retry") as mock_retry:
            mock_retry.side_effect = Retry()

            with pytest.raises(Retry):
                send_hubject_request.delay(
                    payload_json, TestSendHubjectRequest.HUBJECT_URL, "post"
                )

            mock_retry.assert_called_once()

    @responses.activate
    @pytest.mark.django_db
    def test_send_hubject_request_eager_mode_does_not_retry(
        self, payload_json, monkeypatch
    ):
        monkeypatch.setenv("ENV", "production")

        responses.add(
            responses.POST,
            TestSendHubjectRequest.HUBJECT_URL,
            json={"success": False, "error": "hubject error"},
            status=500,
            match=[matchers.json_params_matcher(payload_json)],
        )

        with patch("celery.app.task.Task.request") as mock_request:
            mock_request.is_eager = True
            send_hubject_request.delay(
                payload_json, TestSendHubjectRequest.HUBJECT_URL, "post"
            )

            mock_request.retry.assert_not_called()

    def test_send_hubject_request_unsupported_method(self, mock_client, payload_json):
        mock_client.session.invalid_method = None

        with pytest.raises(NotImplementedError):
            send_hubject_request.delay(
                payload_json, TestSendHubjectRequest.HUBJECT_URL, "invalid_method"
            )
