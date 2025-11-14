import os
import ssl
import subprocess
import tempfile
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from unittest.mock import patch

import pytest
import requests
from asgiref.sync import sync_to_async

from ocpi22.ssl_services import load_ssl_context
from ocpi22.tasks import (
    get_cert_from_env,
    _get_ssl_session_client,
    get_certificate_loaded_request,
)
from ocpi22.tests.factories import CredentialsFactory
from ocpi22.tokens.token_async import create_ssl_context


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
                "/CN=localhost",
            ],
            check=True,
        )

        with open(cert_path, "r") as f:
            cert = f.read()
        with open(key_path, "r") as f:
            key = f.read()

        return cert, key, cert


def run_https_server(server):
    server.serve_forever()


class ClientCertHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        peer_cert = self.connection.getpeercert()
        if peer_cert:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Client cert received")
        else:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"No client cert received")


def to_env_format(pem: str) -> str:
    return "".join(f"{line}\\n" for line in pem.strip().splitlines())


@pytest.fixture
def mock_env_certs(monkeypatch):
    cert, key, ca = generate_cert_and_key()
    monkeypatch.setenv("CLIENT_CERT", to_env_format(cert))
    monkeypatch.setenv("PRIVATE_KEY", to_env_format(key))
    monkeypatch.setenv("CA_CERT", to_env_format(ca))
    return cert, key, ca


@pytest.fixture
def cert_file_paths():
    cert, key, ca = generate_cert_and_key()

    cert_file = tempfile.NamedTemporaryFile(delete=False, mode="w")
    key_file = tempfile.NamedTemporaryFile(delete=False, mode="w")
    ca_file = tempfile.NamedTemporaryFile(delete=False, mode="w")

    cert_file.write(cert)
    key_file.write(key)
    ca_file.write(ca)

    cert_file.flush()
    key_file.flush()
    ca_file.flush()

    return cert, key, ca, cert_file.name, key_file.name, ca_file.name


class TestSSLContextLoader:
    def test_ssl_context_loads(self, mock_env_certs):
        client_cert = get_cert_from_env("CLIENT_CERT")
        private_key = get_cert_from_env("PRIVATE_KEY")
        ca_cert = get_cert_from_env("CA_CERT")

        context = load_ssl_context(client_cert, private_key, ca_cert)
        assert isinstance(context, ssl.SSLContext)

    def test_load_ssl_context_raises_error_with_malformed_certs(self):
        client_cert = "-----BEGIN CERTIFICATE-----\ninvalid\n-----END CERTIFICATE-----"
        private_key = "-----BEGIN PRIVATE KEY-----\nnotakey\n-----END PRIVATE KEY-----"
        ca_cert = "-----BEGIN CERTIFICATE-----\nnotaca\n-----END CERTIFICATE-----"

        with pytest.raises(ssl.SSLError):
            load_ssl_context(client_cert, private_key, ca_cert)

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_loads_valid_context(self, mock_env_certs):
        creds = await sync_to_async(CredentialsFactory)(
            client_certificate_name="CLIENT_CERT",
            private_key_name="PRIVATE_KEY",
            ca_certificate_name="CA_CERT",
        )

        ssl_context = await create_ssl_context(creds.id)

        assert isinstance(ssl_context, ssl.SSLContext)
        assert ssl_context.verify_mode == ssl.CERT_REQUIRED


class TestSessionClient:
    def test_ssl_session_client_mounts_ssl_context(self, mock_env_certs):
        client_cert = get_cert_from_env("CLIENT_CERT")
        private_key = get_cert_from_env("PRIVATE_KEY")
        ca_cert = get_cert_from_env("CA_CERT")

        session = _get_ssl_session_client(client_cert, private_key, ca_cert)

        https_adapter = session.adapters.get("https://")
        ssl_context = getattr(https_adapter.poolmanager, "connection_pool_kw", {}).get(
            "ssl_context"
        )

        assert isinstance(session, requests.Session)
        assert isinstance(ssl_context, ssl.SSLContext)

    def test_ssl_session_client_without_certs_returns_plain_session(self):
        session = _get_ssl_session_client("", "", "")

        https_adapter = session.adapters.get("https://")
        ssl_context = getattr(https_adapter.poolmanager, "connection_pool_kw", {}).get(
            "ssl_context"
        )

        assert isinstance(session, requests.Session)
        assert ssl_context is None


class TestRequestSession:
    def test_get_request_session_returns_plain_session_when_no_credentials(self):
        with patch(
            "ocpi22.models.credentials.Credentials.objects.filter"
        ) as mock_filter:
            mock_filter.return_value.first.return_value = None

            session = get_certificate_loaded_request(credential_id="non-existent-id")

            https_adapter = session.adapters.get("https://")
            ssl_context = getattr(
                https_adapter.poolmanager, "connection_pool_kw", {}
            ).get("ssl_context")

            assert isinstance(session, requests.Session)
            assert ssl_context is None

    def test_get_request_session_raises_with_invalid_certs(self, monkeypatch, db):
        monkeypatch.setenv(
            "BAD_CLIENT_CERT",
            "-----BEGIN CERTIFICATE-----\ninvalid\n-----END CERTIFICATE-----",
        )
        monkeypatch.setenv(
            "BAD_PRIVATE_KEY",
            "-----BEGIN PRIVATE KEY-----\nnotakey\n-----END PRIVATE KEY-----",
        )
        monkeypatch.setenv(
            "BAD_CA_CERT",
            "-----BEGIN CERTIFICATE-----\nnotaca\n-----END CERTIFICATE-----",
        )

        creds = CredentialsFactory(
            client_certificate_name="BAD_CLIENT_CERT",
            private_key_name="BAD_PRIVATE_KEY",
            ca_certificate_name="BAD_CA_CERT",
        )

        with pytest.raises(ssl.SSLError):
            get_certificate_loaded_request(creds.id)


class TestClientCertificateRequest:
    def start_https_server(self, cert_path, key_path, ca_path):
        self._server = HTTPServer(("localhost", 4443), ClientCertHandler)
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_cert_chain(certfile=cert_path, keyfile=key_path)
        context.load_verify_locations(cafile=ca_path)
        self._server.socket = context.wrap_socket(self._server.socket, server_side=True)

        self._thread = threading.Thread(
            target=run_https_server, args=(self._server,), daemon=True
        )
        self._thread.start()

    def stop_https_server(self):
        self._server.shutdown()
        self._thread.join(timeout=1)

    def test_https_server_receives_client_cert(self, cert_file_paths, monkeypatch, db):
        cert, key, ca, cert_path, key_path, ca_path = cert_file_paths
        self.start_https_server(cert_path, key_path, ca_path)

        monkeypatch.setenv("CLIENT_CERT", to_env_format(cert))
        monkeypatch.setenv("PRIVATE_KEY", to_env_format(key))
        monkeypatch.setenv("CA_CERT", to_env_format(ca))

        creds = CredentialsFactory(
            client_certificate_name="CLIENT_CERT",
            private_key_name="PRIVATE_KEY",
            ca_certificate_name="CA_CERT",
        )

        session = get_certificate_loaded_request(creds.id)
        response = session.get("https://localhost:4443", verify=ca_path)

        assert response.status_code == 200
        assert b"Client cert received" in response.content

        self.stop_https_server()
