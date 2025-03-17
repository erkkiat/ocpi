import ssl
import tempfile
import os
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from requests.adapters import HTTPAdapter


class SSLAdapter(HTTPAdapter):
    """Adapter to use a custom SSLContext if provided."""

    def __init__(self, ssl_context=None):
        self.ssl_context = ssl_context
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        if self.ssl_context:
            kwargs["ssl_context"] = self.ssl_context  # Inject SSLContext
        super().init_poolmanager(*args, **kwargs)


def load_ssl_context(cert_str=None, key_str=None):
    """
    Load an SSL context from in-memory certificate and key strings.
    If no cert/key is provided, returns None (default SSL behavior).
    """
    if not cert_str or not key_str:
        return None  # Use system defaults (no custom certs)

    cert = x509.load_pem_x509_certificate(cert_str.encode(), default_backend())
    key = serialization.load_pem_private_key(
        key_str.encode(), password=None, backend=default_backend()
    )

    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
    key_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )

    with (
        tempfile.NamedTemporaryFile(delete=False) as cert_file,
        tempfile.NamedTemporaryFile(delete=False) as key_file,
    ):
        cert_file.write(cert_bytes)
        key_file.write(key_bytes)
        cert_file_path = cert_file.name
        key_file_path = key_file.name

    ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ssl_context.load_cert_chain(certfile=cert_file_path, keyfile=key_file_path)

    # ✅ Delete the temporary files immediately
    os.unlink(cert_file_path)
    os.unlink(key_file_path)

    return ssl_context
