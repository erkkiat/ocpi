import base64
from unittest.mock import patch

import time_machine
from rest_framework import status

from ocpi22.credentials.versions import get_versions_dict, get_endpoints_dict
from ocpi22.models.credentials import Credentials
from ocpi22.ocpi.api import CredentialsViewSet
from ocpi22.ocpi.headers import make_headers
from ocpi22.ocpi.serializers import CredentialsSerializer
from ocpi22.ocpi.util import generate_session_uid
from ocpi22.test_data import CredentialsData
from ocpi22.tests import faketime, BetterTestCase
from ocpiconnector.testutil import OCPIAPIRequestFactory, simulate_surrounding_world, FakeResponse
from util import reverse

api_factory = OCPIAPIRequestFactory()


class UtilTests(BetterTestCase):
    def test_generate_reference(self):
        reference = generate_session_uid()
        self.assertEqual(reference[:6], 'FI*CPO', 'Session UIDs should contain the CPO identity')


class CredentialsTests(BetterTestCase):
    fixtures = ['ocpi22/data/credentials-registration-test.json']

    def test_credentials(self):
        request = self.client.get('/ocpi/credentials/')
        result = CredentialsViewSet().list(request)
        self.assertEqual(result.status_code, 405, 'Credentials should not be accessible without OCPI authentication')

    @simulate_surrounding_world
    def test_credentials_post(self, simulation):
        token_a = '123'
        token_base64 = base64.b64encode(str(token_a).encode('ascii')).decode('ascii')

        simulation.ocpi_requests.get.side_effect = [
            FakeResponse(data=dict(data=get_versions_dict()), status_code=status.HTTP_200_OK),
            FakeResponse(data=dict(data=get_endpoints_dict(version='2.2.1')), status_code=status.HTTP_200_OK)
        ]

        request = api_factory.post(
            reverse('credentials-list'),
            data=CredentialsData.example,
            **make_headers(token_base64)
        )
        request.data = CredentialsData.example
        random_token = '12345'
        with time_machine.travel(faketime, tick=False), \
                patch('ocpi22.ocpi.api.generate_random_token', return_value=random_token):
            credentials = Credentials.objects.create(token_a=token_a)
            result = CredentialsViewSet().post(request)

        serializer = CredentialsSerializer(data=result.data.get('data'))
        self.assertTrue(serializer.is_valid(), f'Credentials POST response should be valid: {serializer.errors}')
        self.assertDictEqual(result.data, CredentialsData.credentials_post_response)

        self.assertEqual(result.status_code, status.HTTP_201_CREATED,
                         'Credentials should be POSTable using token_a')

        credentials = Credentials.objects.get(ours=random_token)
        self.assertDictEqual(credentials.__dict__, CredentialsData.registered_credentials)
