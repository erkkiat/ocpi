import pytest

import responses
from responses import matchers

from ocpi22.tasks import send_hubject_request


class TestSendHubjectRequest:
    HUBJECT_URL = "https://hubject-api.com/endpoint"

    @pytest.fixture
    def payload_json(self):
        return {"key": "value"}

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

        result = send_hubject_request(payload_json, TestSendHubjectRequest.HUBJECT_URL)
        assert result == {"success": True}
