import os
import subprocess
import tempfile
import urllib.parse
from unittest.mock import Mock, patch

import pytest
from cryptography.hazmat._oid import ExtendedKeyUsageOID, NameOID
from django.http import HttpRequest
from django.test import override_settings
from ninja.errors import HttpError

from ocpi22.ocpi.auth import CertificateAuth


def generate_cert_and_key():
    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = os.path.join(tmpdir, "key.pem")
        cert_path = os.path.join(tmpdir, "cert.pem")

        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-nodes",
                "-newkey",
                "rsa:2048",
                "-keyout",
                key_path,
                "-out",
                cert_path,
                "-days",
                "3650",
                "-subj",
                "/CN=test-client/O=TestOrg/OU=TestUnit",
            ],
            check=True,
        )

        with open(cert_path, "r") as f:
            cert = f.read()
        with open(key_path, "r") as f:
            key = f.read()

        return cert, key


@pytest.fixture
def mock_request():
    request = Mock(spec=HttpRequest)
    request.META = {"REMOTE_ADDR": "192.168.1.100"}
    request.headers = {}
    return request


@pytest.fixture
def test_certificates():
    return generate_cert_and_key()


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

    @override_settings(HUBJECT_HOSTS=["10.0.0.1", "192.168.1.100"])
    def test_get_ip_address_raises_forbidden_when_ip_not_allowed(self, mock_request):
        mock_request.META = {"REMOTE_ADDR": "192.168.1.110"}

        auth = ConcreteCertificateAuth(ca_certificate="test-ca")

        with pytest.raises(HttpError) as exc_info:
            auth._get_ip_address(mock_request)

        assert exc_info.value.status_code == 403
        assert "not allowed" in str(exc_info.value)

    def test_load_all_certificates_parses_single_certificate(self, test_certificates):
        cert, _ = test_certificates
        auth = ConcreteCertificateAuth(ca_certificate=cert)

        result = auth._load_all_certificates(cert)

        assert len(result) == 1
        certificate = result[0]
        assert (
            certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
            == "test-client"
        )
        assert certificate.public_key() is not None

    def test_load_all_certificates_parses_certificate_chain(self, test_certificates):
        cert, _ = test_certificates
        cert_chain = f"{cert}\n{cert}"
        auth = ConcreteCertificateAuth(ca_certificate=cert)

        result = auth._load_all_certificates(cert_chain)

        assert len(result) == 2

    def test_authenticate_raises_forbidden_when_no_certificate_header(
        self, mock_request
    ):
        auth = ConcreteCertificateAuth(ca_certificate="test-ca")

        with patch.object(auth, "_get_ip_address", return_value="192.168.1.100"):
            with pytest.raises(HttpError) as exc_info:
                auth.authenticate(mock_request)

        assert exc_info.value.status_code == 403
        assert "No client certificate provided" in str(exc_info.value)

    def test_authenticate_raises_forbidden_when_certificate_format_invalid(
        self, mock_request
    ):
        mock_request.headers = {"X-Amzn-Mtls-Clientcert": "invalid-cert-data"}
        auth = ConcreteCertificateAuth(ca_certificate="test-ca")

        with patch.object(auth, "_get_ip_address", return_value="192.168.1.100"):
            with pytest.raises(HttpError) as exc_info:
                auth.authenticate(mock_request)

        assert exc_info.value.status_code == 403
        assert "Invalid client certificate format" in str(exc_info.value)
