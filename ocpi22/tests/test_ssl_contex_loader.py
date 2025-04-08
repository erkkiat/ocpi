import os
import ssl
import subprocess
import tempfile

import pytest

from ocpi22.ssl_services import load_ssl_context
from ocpi22.tasks import get_cert_from_env


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
    # Minimal dummy certs (valid structure, not cryptographically functional)
    cert, key, ca = generate_cert_and_key()
    print("Cert:", cert)

    monkeypatch.setenv("CLIENT_CERT", to_env_format(cert))
    monkeypatch.setenv("PRIVATE_KEY", to_env_format(key))
    monkeypatch.setenv("CA_CERT", to_env_format(ca))


def test_ssl_context_loads(mock_env_certs):
    client_cert = get_cert_from_env("CLIENT_CERT")
    private_key = get_cert_from_env("PRIVATE_KEY")
    ca_cert = get_cert_from_env("CA_CERT")
    context = load_ssl_context(client_cert, private_key, ca_cert)
    assert isinstance(context, ssl.SSLContext)
