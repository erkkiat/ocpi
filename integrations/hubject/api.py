import os
from collections import defaultdict
from typing import List, Dict

import requests

from urllib.parse import urljoin

from ninja import NinjaAPI

from django.conf import settings

import httpx

from integrations.hubject.schemas import (
    ERoamingPushEvseData,
    ActionType,
    OperatorEvseData,
)
from integrations.ocpi_to_hubject_converter import OCPIToHubjectConverter
from ocpi22.models.location import Location
from util import with_trailing_slash

api = NinjaAPI()


class HubJectClient:
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


@api.get("/alive", url_name="alive")
def check_hubject_alive(request):
    try:
        client = HubJectClient()
        response = client.get(with_trailing_slash(settings.HUBJECT_URL))
        response.raise_for_status()
    except httpx.HTTPError as exc:
        print(exc)
        return {
            "success": False,
            "error": "Failed to connect to Hubject",
        }
    return {"success": True, "message": "Successfully connected to Hubject"}


@api.post("/full-load/", url_name="hubject-evse-full-load")
# @api.post("/full_load/", url_name="hubject-evse-full-load", auth=JWTAuth())
# @permission_classes([IsAdminUser])
# @permission_required('is_admin', raise_exception=True)
def start_evse_full_load(request):
    locations = Location.objects.all()
    converter = OCPIToHubjectConverter()

    collection: Dict[str, List] = defaultdict(list)
    for location in locations:
        op_evse_data = converter.convert_to_operator_evse_data(location)
        collection[op_evse_data.OperatorID.root].append(op_evse_data)

    client = HubJectClient()

    for operator_id, operator_evse_list in collection.items():
        evse_data_record_lists = [
            op_evse_data.EvseDataRecord for op_evse_data in operator_evse_list
        ]
        evse_data_records = [
            evse for evse_list in evse_data_record_lists for evse in evse_list
        ]

        # Create data payload
        data_to_send = ERoamingPushEvseData(
            ActionType=ActionType.fullLoad,
            OperatorEvseData=OperatorEvseData(
                OperatorID=operator_id,
                OperatorName=operator_evse_list[0].OperatorName,
                EvseDataRecord=evse_data_records,
            ),
        )

        full_load_url = urljoin(
            with_trailing_slash(settings.HUBJECT_URL),
            f"evsepush/v23/operators/{data_to_send.OperatorEvseData.OperatorID}/data-records",
        )

        try:
            headers = {"Content-type": "application/json"}
            response = client.post(
                full_load_url, data=data_to_send.model_dump_json(), headers=headers
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            print(exc)
            return {
                "success": False,
                "error": "Failed to full load evses for Operator FI*CPO",
            }

    return response.json()
