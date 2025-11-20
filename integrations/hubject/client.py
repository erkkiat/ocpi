import os
import requests

from django.conf import settings

from ocpi22.tasks import get_cert_from_env


class HubjectClient:
    CLIENT_CERTIFICATE = get_cert_from_env("HUBJECT_CLIENT_CERTIFICATE")
    PRIVATE_KEY = get_cert_from_env("HUBJECT_PRIVATE_KEY")
    CA_CERTIFICATE = get_cert_from_env("HUBJECT_CA_CERTIFICATE")

    def __init__(self, rewrite_cert_files=False):
        self.client_cert_path = os.path.join(
            os.getcwd(),
            "integrations",
            "hubject",
            "certificates",
            "client_certificate.crt",
        )
        self.key_path = os.path.join(
            os.getcwd(),
            "integrations",
            "hubject",
            "certificates",
            "private.key",
        )

        self.ca_cert_path = os.path.join(
            os.getcwd(),
            "integrations",
            "hubject",
            "certificates",
            "ca_certificate.crt",
        )

        if (
            rewrite_cert_files
            or not os.path.isfile(self.client_cert_path)
            or not os.path.isfile(self.key_path)
            or not os.path.isfile(self.ca_cert_path)
        ):
            self._save_cert_and_key()

        self.session = requests.Session()
        self.session.cert = (self.client_cert_path, self.key_path)
        self.session.verify = self.ca_cert_path
        # The Proxy URL is required for hubject. The IP address in Proxy URL is whitelisted in Hubject QA Env.
        self.session.proxies = {"http": settings.FIXIE_URL, "https": settings.FIXIE_URL}

    def _save_cert_and_key(self):
        if not self.CLIENT_CERTIFICATE or not self.PRIVATE_KEY:
            raise ValueError(
                "Certificate or key data not found in environment variables"
            )
        os.makedirs(
            os.path.join(
                os.getcwd(),
                "integrations",
                "hubject",
                "certificates",
            ),
            exist_ok=True,
        )

        cert_files = (
            (self.client_cert_path, self.CLIENT_CERTIFICATE),
            (self.key_path, self.PRIVATE_KEY),
            (self.ca_cert_path, self.CA_CERTIFICATE),
        )
        for path, content in cert_files:
            with open(path, "w") as cert_file:
                cert_file.write(content)

    def get(self, url, **kwargs):
        return self.session.get(url, **kwargs)

    def post(self, url, data=None, json=None, **kwargs):
        return self.session.post(url, data=data, json=json, **kwargs)

    def put(self, url, data=None, json=None, **kwargs):
        return self.session.put(url, data=data, json=json, **kwargs)

    def patch(self, url, data=None, json=None, **kwargs):
        return self.session.patch(url, data=data, json=json, **kwargs)
