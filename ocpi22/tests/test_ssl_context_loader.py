import os
import ssl
import subprocess
import tempfile
from unittest.mock import patch

import pytest
import requests

from ocpi22.ssl_services import load_ssl_context
from ocpi22.tasks import get_cert_from_env, _get_ssl_session_client, get_request_session


def generate_cert_and_key():
    # Create a temp dir to store generated files
    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = os.path.join(tmpdir, "key.pem")
        cert_path = os.path.join(tmpdir, "cert.pem")

        # Generate a self-signed certificate using OpenSSL
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
                "/CN=Test Cert",
            ],
            check=True,
        )

        # Read the cert and key contents
        with open(cert_path, "r") as f:
            cert = f.read()
        with open(key_path, "r") as f:
            key = f.read()

        # For testing, the CA is the same as the cert
        return cert, key, cert


def to_env_format(pem: str) -> str:
    return "".join(f"{line}\\n" for line in pem.strip().splitlines())


@pytest.fixture
def mock_env_certs(monkeypatch):
    cert, key, ca = generate_cert_and_key()

    monkeypatch.setenv("CLIENT_CERT", to_env_format(cert))
    monkeypatch.setenv("PRIVATE_KEY", to_env_format(key))
    monkeypatch.setenv("CA_CERT", to_env_format(ca))


def test_ssl_context_loads(mock_env_certs):
    client_cert = get_cert_from_env("CLIENT_CERT")
    private_key = get_cert_from_env("PRIVATE_KEY")
    ca_cert = get_cert_from_env("CA_CERT")
    context = load_ssl_context(client_cert, private_key, ca_cert)
    assert isinstance(context, ssl.SSLContext)


def test_ssl_session_client_mounts_ssl_context(mock_env_certs):
    client_cert = get_cert_from_env("CLIENT_CERT")
    private_key = get_cert_from_env("PRIVATE_KEY")
    ca_cert = get_cert_from_env("CA_CERT")

    session = _get_ssl_session_client(client_cert, private_key, ca_cert)

    https_adapter = session.adapters.get("https://")

    ssl_context = getattr(https_adapter.poolmanager, "connection_pool_kw", {}).get(
        "ssl_context", None
    )

    assert isinstance(session, requests.Session)
    assert isinstance(ssl_context, ssl.SSLContext)


def test_get_request_session_returns_plain_session_when_no_credentials():
    with patch("ocpi22.models.credentials.Credentials.objects.filter") as mock_filter:
        mock_filter.return_value.first.return_value = None

        session = get_request_session(credential_id="non-existent-id")

        assert isinstance(session, requests.Session)

        https_adapter = session.adapters.get("https://")

        ssl_context = getattr(https_adapter.poolmanager, "connection_pool_kw", {}).get(
            "ssl_context", None
        )

        assert ssl_context is None


def test__get_ssl_session_client_without_certs_returns_plain_session():
    session = _get_ssl_session_client("", "", "")

    assert isinstance(session, requests.Session)

    https_adapter = session.adapters.get("https://")
    ssl_context = getattr(https_adapter.poolmanager, "connection_pool_kw", {}).get(
        "ssl_context", None
    )
    assert ssl_context is None


def test_ssl_context_fails_with_malformed_certs():
    malformed_cert = (
        "-----BEGIN CERTIFICATE-----\\nthis-is-not-valid\\n-----END CERTIFICATE-----"
    )
    malformed_key = (
        "-----BEGIN PRIVATE KEY-----\\ninvalid-key-content\\n-----END PRIVATE KEY-----"
    )
    malformed_ca = (
        "-----BEGIN CERTIFICATE-----\\ncorrupt-ca\\n-----END CERTIFICATE-----"
    )

    # Decode as the app would do
    client_cert = malformed_cert.replace("\\n", "\n")
    private_key = malformed_key.replace("\\n", "\n")
    ca_cert = malformed_ca.replace("\\n", "\n")

    with pytest.raises(ssl.SSLError):
        load_ssl_context(client_cert, private_key, ca_cert)
