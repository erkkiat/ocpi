import base64
import pytest
from unittest.mock import patch

import responses

from ocpi22.tests.factories import CredentialsFactory
from ocpiconnector.management.commands.exchange_credentials import Command
from ocpi22.ocpi.api import CredentialsViewSet
from ocpiconnector.testutil import OCPIAPIRequestFactory
from ocpi22.ocpi.headers import make_headers
from util import reverse


@pytest.mark.django_db
class TestDisableTokenA:
    @responses.activate
    def test_exchange_credentials_command(self):
        """Test that exchange_credentials.py calls disable_token_a()"""
        token_a = "token_a_123456"
        our_token = "our_token_123456"
        their_token = "their_token_123456"
        versions_url = "https://testserver.test/ocpi/versions"
        endpoints_221_url = "https://testserver.test/ocpi/2.2.1/"

        responses.add(
            responses.GET,
            versions_url,
            json={"data": [{"version": "2.2.1", "url": endpoints_221_url}]},
            status=200,
        )

        responses.add(
            responses.GET,
            endpoints_221_url,
            json={
                "data": {
                    "version": "2.2.1",
                    "endpoints": [
                        {
                            "identifier": "credentials",
                            "role": "receiver",
                            "url": "https://testserver.test/ocpi/credentials",
                        }
                    ],
                }
            },
            status=200,
        )

        responses.add(
            responses.POST,
            "https://testserver.test/ocpi/credentials",
            json={
                "data": {
                    "token": their_token,
                    "url": versions_url,
                    "roles": [
                        {
                            "role": "CPO",
                            "country_code": "NL",
                            "party_id": "EXA",
                            "business_details": {
                                "name": "Test",
                                "website": "http://testserver.test/",
                            },
                        }
                    ],
                }
            },
            status=201,
        )

        credentials = CredentialsFactory(
            token_a=token_a, ours=our_token, theirs=their_token
        )

        with (
            patch(
                "ocpiconnector.management.commands.exchange_credentials.generate_random_token",
                return_value=our_token,
            ),
            patch("django.conf.settings.HOSTNAME", "testserver2.test"),
        ):
            command = Command()
            command.handle(token_a=token_a, versions_endpoint_url=versions_url)

            credentials.refresh_from_db()
            assert credentials.token_a == ""
            assert credentials.ours == our_token
            assert credentials.theirs == their_token

    @responses.activate
    def test_credentials_viewset_post(self):
        """Test that CredentialsViewSet.post calls disable_token_a()"""
        token_a = "token_a_123456"
        token_a_base64 = base64.b64encode(token_a.encode("ascii")).decode("ascii")
        our_token = "our_token_123456"
        their_token = "their_token_123456"

        credentials = CredentialsFactory(token_a=token_a, ours="", theirs="")

        request_data = {
            "token": their_token,
            "url": "https://localhost/versions/",
            "roles": [
                {
                    "role": "CPO",
                    "country_code": "NL",
                    "party_id": "EXA",
                    "business_details": {
                        "name": "Test CPO",
                        "website": "https://testserver.test",
                    },
                }
            ],
        }

        api_factory = OCPIAPIRequestFactory()
        headers = make_headers(token_a_base64)
        request = api_factory.post(
            reverse("credentials-list"), data=request_data, **headers
        )
        request.data = request_data
        request.credentials = credentials
        request.version = "2.2.1"

        responses.add(
            responses.GET,
            "https://localhost/versions/",
            json={
                "data": [{"version": "2.2.1", "url": "https://localhost/ocpi/2.2.1/"}]
            },
            status=200,
        )

        responses.add(
            responses.GET,
            "https://localhost/ocpi/2.2.1/",
            json={"data": {"version": "2.2.1", "endpoints": []}},
            status=200,
        )

        with patch("ocpi22.ocpi.api.generate_random_token", return_value=our_token):
            viewset = CredentialsViewSet()
            viewset.post(request)

            credentials.refresh_from_db()
            assert credentials.token_a == ""
            assert credentials.ours == our_token
            assert credentials.theirs == their_token
