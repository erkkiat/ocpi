import ipaddress
import os
import subprocess
import tempfile
import urllib.parse
from unittest.mock import Mock, patch
import datetime

import pytest
import responses
from cryptography import x509
from cryptography.hazmat._oid import ExtendedKeyUsageOID, NameOID
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from django.http import HttpRequest
from django.test import override_settings
from django.urls import reverse
from ninja.errors import HttpError
from rest_framework.test import APIClient

from ocpi22.ocpi.auth import CertificateAuth, HubjectCertAuth, get_credentialsrole
from webhooks.choices import WebhookType, RemoteCommandType
from webhooks.factories import WebhookFactory


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
                "/CN=localhost/O=TestOrg/OU=TestUnit",
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

    def test_get_ip_address_returns_forwarded_ip_when_present(self, mock_request):
        mock_request.META = {"HTTP_X_FORWARDED_FOR": "10.0.0.1, 192.168.1.200"}

        auth = ConcreteCertificateAuth(
            ca_certificate="test-ca", allowed_hosts=["10.0.0.1", "192.168.1.100"]
        )
        result = auth._get_ip_address(mock_request)

        assert result == "10.0.0.1"

    def test_get_ip_address_returns_value_error_for_invalid_ip_address_format(
        self, mock_request
    ):
        mock_request.META = {"HTTP_X_FORWARDED_FOR": "invalid, 192.168.1.200"}

        with pytest.raises(HttpError):
            auth = ConcreteCertificateAuth(
                ca_certificate="test-ca", allowed_hosts=["10.0.0.1", "192.168.1.100"]
            )
            auth._get_ip_address(mock_request)

    def test_get_ip_address_returns_remote_addr_when_forwarded_for_is_empty(
        self, mock_request
    ):
        mock_request.META = {"REMOTE_ADDR": "192.168.1.100"}

        auth = ConcreteCertificateAuth(
            ca_certificate="test-ca", allowed_hosts=["10.0.0.1", "192.168.1.100"]
        )
        result = auth._get_ip_address(mock_request)

        assert result == "192.168.1.100"

    def test_get_ip_address_raises_forbidden_when_ip_not_allowed(self, mock_request):
        mock_request.META = {"REMOTE_ADDR": "192.168.1.110"}

        auth = ConcreteCertificateAuth(
            ca_certificate="test-ca", allowed_hosts=["10.0.0.1", "192.168.1.100"]
        )

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
            == "localhost"
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


class TestHubjectCertAuth:
    def test_hubject_ca_certificate_setting_is_not_set_raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            with patch("ocpi22.ocpi.auth.get_cert_from_env") as get_cert_mock:
                get_cert_mock.return_value = None
                HubjectCertAuth()
        assert "HUBJECT_CA_CERTIFICATE is not in the environment variables" in str(
            exc_info.value
        )

    @override_settings(
        HUBJECT_CA_CERTIFICATE="-----BEGIN CERTIFICATE-----hubject-ca-cert-----END CERTIFICATE-----"
    )
    def test_get_certificate_header_decodes_mtls_header(self, mock_request):
        quoted_cert = urllib.parse.quote("test cert data")
        mock_request.headers = {"X-Amzn-Mtls-Clientcert": quoted_cert}

        auth = HubjectCertAuth()
        result = auth._get_certificate_header(mock_request)

        assert result == "test cert data"

    @override_settings(
        HUBJECT_CA_CERTIFICATE="-----BEGIN CERTIFICATE-----hubject-ca-cert-----END CERTIFICATE-----"
    )
    def test_build_client_verifier_validates_eku_extensions(self):
        from cryptography.x509.verification import Store
        from cryptography import x509

        cert, _ = generate_cert_and_key()
        root_cert = x509.load_pem_x509_certificate(cert.encode())
        store = Store([root_cert])

        verifier = HubjectCertAuth()._build_client_verifier(store)

        assert (
            verifier.policy.extended_key_usage.dotted_string
            == ExtendedKeyUsageOID.CLIENT_AUTH.dotted_string
        )


@pytest.fixture
def hubject_client():
    cert, _, ca = generate_webpki_compliant_certificates()
    client = APIClient()

    cert_header = urllib.parse.quote(cert)
    client.defaults.update(
        {"HTTP_X_AMZN_MTLS_CLIENTCERT": cert_header, "REMOTE_ADDR": "192.168.1.100"}
    )

    return client


def generate_webpki_compliant_certificates():
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "CA"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "TestCity"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TestCA"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Test Root CA"),
        ]
    )

    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(1)
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                key_cert_sign=True,
                crl_sign=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                content_commitment=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    client_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client_name = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "CA"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "TestCity"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TestClient"),
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ]
    )

    client_cert = (
        x509.CertificateBuilder()
        .subject_name(client_name)
        .issuer_name(ca_name)
        .public_key(client_key.public_key())
        .serial_number(2)
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=30))
        # CRITICAL: Set cA=False for end-entity certificates
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=False,
                crl_sign=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                content_commitment=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage(
                [
                    ExtendedKeyUsageOID.CLIENT_AUTH,
                    ExtendedKeyUsageOID.SERVER_AUTH,
                ]
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(client_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    ca_cert_pem = ca_cert.public_bytes(serialization.Encoding.PEM).decode()
    client_cert_pem = client_cert.public_bytes(serialization.Encoding.PEM).decode()
    client_key_pem = client_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    return client_cert_pem, client_key_pem, ca_cert_pem


class TestHubjectCertificateAuthIntegration:
    cert, _, ca = generate_webpki_compliant_certificates()

    @pytest.mark.django_db
    @responses.activate
    @override_settings(
        HUBJECT_CA_CERTIFICATE="-----BEGIN CERTIFICATE-----hubject-ca-cert-----END CERTIFICATE-----"
    )
    def test_hubject_auth_processes_real_https_request_return_200(
        self, remote_command_payload
    ):
        get_credentialsrole.cache_clear()
        hubject_client = APIClient()

        cert_header = urllib.parse.quote(self.cert)
        hubject_client.defaults.update(
            {"HTTP_X_AMZN_MTLS_CLIENTCERT": cert_header, "REMOTE_ADDR": "192.168.1.100"}
        )
        WebhookFactory(
            type=WebhookType.REMOTE_COMMAND,
            command_type=RemoteCommandType.START_SESSION,
            url="http://testserver.test/api/cpo/v2/chargepoint/remote_command_result/MSPSession/",
        )

        responses.add(
            responses.POST,
            "http://testserver.test/api/cpo/v2/chargepoint/remote_command_result/MSPSession/",
            json={"data": {"result": "ACCEPTED"}},
            status=200,
        )

        with patch(
            "ocpi22.ocpi.auth.CertificateAuth._get_ip_address",
            return_value="192.168.1.100",
        ):
            with patch("integrations.hubject.api.hubject_auth.ca_certificate", self.ca):
                url = reverse("hubject-api:hubject-remote-start", args=["DE-DCB"])
                response = hubject_client.post(
                    url, data=remote_command_payload, format="json"
                )

                assert response.status_code == 200
