import ssl
import tempfile
import os
from requests.adapters import HTTPAdapter


class SSLAdapter(HTTPAdapter):
    def __init__(self, ssl_context=None):
        self.ssl_context = ssl_context
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        if self.ssl_context:
            kwargs["ssl_context"] = self.ssl_context
        super().init_poolmanager(*args, **kwargs)


def load_ssl_context(client_cert: str, private_key: str, ca_cert: str, verify_ssl=True):
    if not all([client_cert, private_key, ca_cert]):
        raise ValueError("client_cert, private_key, and ca_cert are required.")

    ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ssl_context.verify_mode = ssl.CERT_REQUIRED if verify_ssl else ssl.CERT_NONE

    cert_file = tempfile.NamedTemporaryFile(delete=False)
    key_file = tempfile.NamedTemporaryFile(delete=False)
    ca_cert_file = tempfile.NamedTemporaryFile(delete=False)

    try:
        cert_file.write(client_cert.encode())
        key_file.write(private_key.encode())
        ca_cert_file.write(ca_cert.encode())

        cert_file.flush()
        key_file.flush()
        ca_cert_file.flush()

        ssl_context.load_cert_chain(certfile=cert_file.name, keyfile=key_file.name)
        ssl_context.load_verify_locations(cafile=ca_cert_file.name)

    finally:
        cert_file.close()
        key_file.close()
        ca_cert_file.close()

        os.unlink(cert_file.name)
        os.unlink(key_file.name)
        os.unlink(ca_cert_file.name)

    return ssl_context
