import pytest
from unittest.mock import patch

import responses

from ocpi22.models.credentials import Credentials
from ocpi22.tests.factories import CredentialsFactory
from ocpiconnector.management.commands.exchange_credentials import Command


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
                "ocpiconnector.management.commands.exchange_credentials.store_tokens_for_party",
                return_value=credentials,
            ),
            patch(
                "ocpiconnector.management.commands.exchange_credentials.store_endpoints_for_party"
            ),
            patch(
                "ocpiconnector.management.commands.exchange_credentials.get_our_roles",
                return_value=[
                    {
                        "role": "CPO",
                        "country_code": "NL",
                        "party_id": "TEST",
                        "business_details": {
                            "name": "Test",
                            "website": "http://testserver.test",
                        },
                    }
                ],
            ),
            patch(
                "ocpiconnector.management.commands.exchange_credentials.build_absolute_uri",
                return_value="http://localhost/versions",
            ),
            patch(
                "ocpiconnector.management.commands.exchange_credentials.reverse",
                return_value="/versions",
            ),
            patch(
                "ocpiconnector.management.commands.exchange_credentials.generate_random_token",
                return_value=our_token,
            ),
            patch("django.conf.settings.HOSTNAME", "testserver2.test"),
            patch.object(Credentials, "disable_token_a") as mock_disable_token_a,
        ):
            command = Command()
            command.handle(token_a=token_a, versions_endpoint_url=versions_url)

            mock_disable_token_a.assert_called_once_with()
