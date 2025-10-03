import urllib.parse
from unittest.mock import Mock

import pytest
from cryptography.hazmat._oid import ExtendedKeyUsageOID
from django.http import HttpRequest
from django.test import override_settings
from ninja.errors import HttpError

from ocpi22.ocpi.auth import CertificateAuth


@pytest.fixture
def mock_request():
    request = Mock(spec=HttpRequest)
    request.META = {"REMOTE_ADDR": "192.168.1.100"}
    request.headers = {}
    return request


class ConcreteCertificateAuth(CertificateAuth):
    def _get_certificate_header(self, request: HttpRequest) -> str:
        return urllib.parse.unquote(request.headers.get("X-Amzn-Mtls-Clientcert", ""))

    def _build_client_verifier(self, store):
        from cryptography.x509.verification import PolicyBuilder

        return PolicyBuilder().store(store).build_client_verifier()


class TestCertificateAuth:
    @pytest.mark.parametrize(
        "require_client_auth,require_server_auth,expected_ekus",
        [
            (False, False, []),
            (True, False, [ExtendedKeyUsageOID.CLIENT_AUTH]),
            (False, True, [ExtendedKeyUsageOID.SERVER_AUTH]),
            (
                True,
                True,
                [ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SERVER_AUTH],
            ),
        ],
    )
    def test_init_sets_proper_eku_when_require_client_auth_true(
        self, require_client_auth, require_server_auth, expected_ekus
    ):
        auth = ConcreteCertificateAuth(
            ca_certificate="test-ca",
            require_client_auth=True,
            require_server_auth=False,
        )

        assert ExtendedKeyUsageOID.CLIENT_AUTH in auth.allowed_ekus
        assert ExtendedKeyUsageOID.SERVER_AUTH not in auth.allowed_ekus

    @override_settings(HUBJECT_HOSTS=["10.0.0.1", "192.168.1.100"])
    def test_get_ip_address_returns_forwarded_ip_when_present(self, mock_request):
        mock_request.META = {"HTTP_X_FORWARDED_FOR": "10.0.0.1, 192.168.1.200"}

        auth = ConcreteCertificateAuth(ca_certificate="test-ca")
        result = auth._get_ip_address(mock_request)

        assert result == "10.0.0.1"

    @override_settings(HUBJECT_HOSTS=["10.0.0.1", "192.168.1.100"])
    def test_get_ip_address_returns_value_error_for_invalid_ip_address_format(
        self, mock_request
    ):
        mock_request.META = {"HTTP_X_FORWARDED_FOR": "invalid, 192.168.1.200"}

        with pytest.raises(HttpError):
            auth = ConcreteCertificateAuth(ca_certificate="test-ca")
            auth._get_ip_address(mock_request)

    @override_settings(HUBJECT_HOSTS=["10.0.0.1", "192.168.1.100"])
    def test_get_ip_address_returns_remote_addr_when_forwarded_for_is_empty(
        self, mock_request
    ):
        mock_request.META = {"REMOTE_ADDR": "192.168.1.100"}

        auth = ConcreteCertificateAuth(ca_certificate="test-ca")
        result = auth._get_ip_address(mock_request)

        assert result == "192.168.1.100"
