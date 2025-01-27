import pytest

from integrations.hubject.client import HubjectClient
import responses


@pytest.fixture
def farm3_url():
    return "https://solidroam-f3.smappee.net/"


class TestHubjectClient:
    def test_hubject_client_init(self):
        HubjectClient(rewrite_cert_files=False)

    @responses.activate
    def test_hubject_post_request_headers(self, farm3_url):
        hubject_client = HubjectClient(rewrite_cert_files=False)

        responses.add(
            responses.POST, farm3_url, json={"message": "Success"}, status=200
        )

        result = hubject_client.post(farm3_url)

        assert result.request.headers["Content-Type"] == "application/json"

    @responses.activate
    def test_hubject_put_request_headers(self, farm3_url):
        hubject_client = HubjectClient(rewrite_cert_files=False)

        responses.add(responses.PUT, farm3_url, json={"message": "Success"}, status=200)

        result = hubject_client.put(farm3_url)

        assert result.request.headers["Content-Type"] == "application/json"

    @responses.activate
    def test_hubject_patch_request_headers(self, farm3_url):
        hubject_client = HubjectClient(rewrite_cert_files=False)

        responses.add(
            responses.PATCH, farm3_url, json={"message": "Success"}, status=200
        )

        result = hubject_client.patch(farm3_url)

        assert result.request.headers["Content-Type"] == "application/json"

    @responses.activate
    def test_hubject_get_request_headers(self, farm3_url):
        hubject_client = HubjectClient(rewrite_cert_files=False)

        responses.add(responses.GET, farm3_url, json={"message": "Success"}, status=200)

        result = hubject_client.get(farm3_url)

        pytest.raises(KeyError, lambda: result.request.headers["Content-Type"])
