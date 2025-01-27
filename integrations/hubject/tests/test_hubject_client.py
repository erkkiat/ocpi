import pytest

from integrations.hubject.client import HubjectClient
import responses


class TestHubjectClient:
    def test_hubject_client_init(self):
        HubjectClient(rewrite_cert_files=False)

    @responses.activate
    def test_hubject_post_request_headers(self):
        hubject_client = HubjectClient(rewrite_cert_files=False)

        test_url = "https://solidroam-f3.smappee.net/"

        responses.add(responses.POST, test_url, json={"message": "Success"}, status=200)

        result = hubject_client.post(test_url)

        assert result.request.headers["Content-Type"] == "application/json"

    @responses.activate
    def test_hubject_get_request_headers(self):
        hubject_client = HubjectClient(rewrite_cert_files=False)

        test_url = "https://solidroam-f3.smappee.net/"

        responses.add(responses.GET, test_url, json={"message": "Success"}, status=200)

        result = hubject_client.get(test_url)

        pytest.raises(KeyError, lambda: result.request.headers["Content-Type"])
