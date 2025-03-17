import ssl
import tempfile
import os
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


def load_ssl_context(client_cert: str, private_key: str, ca_cert: str, verify_ssl=True):
    if not all([client_cert, private_key, ca_cert]):
        raise ValueError("cert_str, key_str, and ca_cert_str are required.")

    ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)

    ssl_context.verify_mode = ssl.CERT_REQUIRED if verify_ssl else ssl.CERT_NONE

    with (
        tempfile.NamedTemporaryFile(delete=False) as cert_file,
        tempfile.NamedTemporaryFile(delete=False) as key_file,
        tempfile.NamedTemporaryFile(delete=False) as ca_cert_file,
    ):
        cert_file.write(client_cert.encode())
        key_file.write(private_key.encode())
        ca_cert_file.write(ca_cert.encode())

        cert_file_path = cert_file.name
        key_file_path = key_file.name
        ca_cert_file_path = ca_cert_file.name

    ssl_context.load_cert_chain(certfile=cert_file_path, keyfile=key_file_path)
    ssl_context.load_verify_locations(cafile=ca_cert_file_path)

    os.unlink(cert_file_path)
    os.unlink(key_file_path)
    os.unlink(ca_cert_file_path)

    return ssl_context
