import os
import requests

from django.conf import settings


class HubjectClient:
    CLIENT_CERTIFICATE = settings.HUBJECT_CLIENT_CERTIFICATE
    PRIVATE_KEY = settings.HUBJECT_PRIVATE_KEY
    CA_CERTIFICATE = settings.HUBJECT_CA_CERTIFICATE

    def __init__(
        self,
    ):
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
            not os.path.isfile(self.client_cert_path)
            or not os.path.isfile(self.key_path)
            or not os.path.isfile(self.ca_cert_path)
        ):
            self._save_cert_and_key()

        self.session = requests.Session()
        self.session.cert = (self.client_cert_path, self.key_path)
        self.session.verify = self.ca_cert_path

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

        with open(self.client_cert_path, "w") as cert_file:
            cert_file.write(self.CLIENT_CERTIFICATE)

        with open(self.key_path, "w") as key_file:
            key_file.write(self.PRIVATE_KEY)

        with open(self.ca_cert_path, "w") as key_file:
            key_file.write(self.CA_CERTIFICATE)

    def get(self, url, **kwargs):
        return self.session.get(url, **kwargs)

    def post(self, url, data=None, json=None, **kwargs):
        return self.session.post(url, data=data, json=json, **kwargs)

    def put(self, url, data=None, json=None, **kwargs):
        return self.session.put(url, data=data, json=json, **kwargs)

    def patch(self, url, data=None, json=None, **kwargs):
        return self.session.patch(url, data=data, json=json, **kwargs)
