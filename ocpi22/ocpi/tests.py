import base64
from unittest.mock import patch

import time_machine
from django.core.handlers.wsgi import WSGIRequest
from rest_framework import status

from ocpi22.credentials.versions import get_versions_dict, get_endpoints_dict
from ocpi22.models.credentials import Credentials, CredentialsRole
from ocpi22.ocpi.api import CredentialsViewSet
from ocpi22.ocpi.headers import make_headers
from ocpi22.ocpi.partners import (
    add_partner,
    get_partners_by_party_as_party,
    remove_partner,
)
from ocpi22.ocpi.serializers import CredentialsSerializer
from ocpi22.ocpi.util import generate_session_uid
from ocpi22.test_data import CredentialsData
from ocpi22.tests import faketime, BetterTestCase
from ocpiconnector.ocpi_identities import Party
from ocpiconnector.testutil import (
    OCPIAPIRequestFactory,
    simulate_surrounding_world,
    FakeResponse,
    compare_dicts_recursively,
)
from util import reverse

api_factory = OCPIAPIRequestFactory()


class UtilTests(BetterTestCase):
    def test_generate_reference(self):
        reference = generate_session_uid()
        self.assertEqual(
            reference[:6], "FI*CPO", "Session UIDs should contain the CPO identity"
        )


class CredentialsTests(BetterTestCase):
    fixtures = ["ocpi22/data/credentials-registration-test.json"]

    def test_credentials(self):
        request = self.client.get("/ocpi/credentials/")
        result = CredentialsViewSet().list(request)
        self.assertEqual(
            result.status_code,
            405,
            "Credentials should not be accessible without OCPI authentication",
        )

    @staticmethod
    def make_request(
        data: dict, token_base64=None, url_name="credentials-list"
    ) -> WSGIRequest:
        assert isinstance(data, dict)
        headers = make_headers(token_base64)
        request: WSGIRequest = api_factory.post(reverse(url_name), data=data, **headers)
        request._full_data = data
        setattr(request, "data", data)
        return request

    @simulate_surrounding_world
    def test_credentials_post(self, simulation):
        token_a = "123"
        token_base64 = base64.b64encode(str(token_a).encode("ascii")).decode("ascii")

        simulation.ocpi_requests.get.side_effect = [
            # Response to the first GET ( /versions )
            FakeResponse(
                data=dict(data=get_versions_dict()), status_code=status.HTTP_200_OK
            ),
            # Response to the second GET ( /versions/2.2.1/endpoints )
            FakeResponse(
                data=dict(data=get_endpoints_dict(version="2.2.1")),
                status_code=status.HTTP_200_OK,
            ),
        ]

        request = self.make_request(CredentialsData.example, token_base64=token_base64)
        random_token = "12345"

        with (
            time_machine.travel(faketime, tick=False),
            patch("ocpi22.ocpi.api.generate_random_token", return_value=random_token),
        ):
            result = CredentialsViewSet().post(request)

        credentials = Credentials.objects.get(pk=2)
        self.assertFalse(credentials.token_a, "Token A should have been cleared")
        self.assertEqual(
            credentials.roles.count(), 2, "Credentials should have two roles"
        )
        first_role: CredentialsRole = credentials.roles.first()
        self.assertEqual(
            first_role.country_code, "NL", "Expecting different country code"
        )
        self.assertEqual(first_role.party_id, "EXA", "Expecting different party ID")

        serializer = CredentialsSerializer(data=result.data.get("data"))
        self.assertTrue(
            serializer.is_valid(),
            f"Credentials POST response should be valid: {serializer.errors}",
        )
        self.assertTrue(
            compare_dicts_recursively(
                result.data, CredentialsData.credentials_post_response
            )
        )

        self.assertEqual(
            result.status_code,
            status.HTTP_201_CREATED,
            "Credentials should be POSTable using token_a",
        )

        credentials = Credentials.objects.get(ours=random_token)
        self.assertDictEqual(
            credentials.__dict__, CredentialsData.registered_credentials
        )

        # Updating an existing Credentials using POST should fail
        with simulation.assert_error_logged("use PUT to update"):
            result = CredentialsViewSet().post(request)

        self.assertTrue(
            result.status_code == status.HTTP_400_BAD_REQUEST,
            "Updating an existing credentials should fail",
        )
        self.assertTrue(
            "Credentials exist" in result.data.get("status_message", ""),
            "Updating an existing credentials should fail",
        )


class PartnerTests(BetterTestCase):
    fixtures = ["ocpi22/data/credentials.json"]

    @simulate_surrounding_world
    def test_agreed_partner_add_and_remove(self, simulation):
        p1 = Party("FI", "CPO")  # Does not exist in the database
        p2 = Party("FI", "MSP")
        p3 = Party("FI", "000")
        p4 = Party("FI", "NAP")

        # ic(CredentialsRole.objects.all())

        with self.assertRaises(ValueError):
            add_partner(p1, p2)

        # Check that all parties have no partners yet
        self.assertFalse(all(get_partners_by_party_as_party(x) for x in [p1, p2, p3]))

        # Add a partner and check that the partners are correct
        add_partner(p3, p2)
        self.assertEqual(
            get_partners_by_party_as_party(p3),
            {p2},
            "FI*000 should now be partners with FI*MSP",
        )
        self.assertEqual(
            get_partners_by_party_as_party(p2),
            {p3},
            "FI*MSP should now be partners with FI*000",
        )

        # Add another partner and check that the partners are correct
        add_partner(p3, p4)
        self.assertSetEqual(
            get_partners_by_party_as_party(p3),
            {p2, p4},
            "FI*000 should now be partners with FI*MSP and FI*NAP",
        )
        self.assertEqual(
            get_partners_by_party_as_party(p4),
            {p3},
            "FI*NAP should now be partners with FI*000",
        )
        self.assertEqual(
            get_partners_by_party_as_party(p2),
            {p3},
            "FI*MSP should now be partners with FI*000",
        )

        # Remove a partner and check that the partners are correct
        remove_partner(p3, p2)
        self.assertEqual(
            get_partners_by_party_as_party(p3),
            {p4},
            "FI*000 should now only be partners with FI*NAP",
        )
