from unittest import TestCase

from ocpi22.ocpi.util import generate_session_uid


class UtilTests(TestCase):
    def test_generate_reference(self):
        reference = generate_session_uid()
        self.assertEqual(reference[:6], 'FI*CPO', 'Session UIDs should contain the CPO identity')
