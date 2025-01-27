from integrations.hubject.client import HubjectClient
import responses


class TestHubjectClient:
    def test_hubject_client_init(self):
        HubjectClient(rewrite_cert_files=False)

    @responses.activate
    def test_hubject_post_request_headers(self):
        hubject_client = HubjectClient(rewrite_cert_files=False)

        test_url = "https://solidroam.smappee.net/"

        responses.add(responses.POST, test_url, json={"message": "Success"}, status=200)

        result = hubject_client.post(test_url)

        assert result.request.headers["Content-Type"] == "application/json"
