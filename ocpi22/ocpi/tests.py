from django.test import TestCase
from ocpi22.ocpi.api import CredentialsViewSet
from ocpi22.ocpi.util import generate_session_uid


class UtilTests(TestCase):
    def test_generate_reference(self):
        reference = generate_session_uid()
        self.assertEqual(reference[:6], 'FI*CPO', 'Session UIDs should contain the CPO identity')


class CredentialsTests(TestCase):
    def test_credentials(self):
        request = self.client.get('/ocpi/credentials/')
        result = CredentialsViewSet().list(request)
        self.assertEqual(result.status_code, 405, 'Credentials should not be accessible without OCPI authentication')