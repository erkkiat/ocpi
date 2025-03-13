import json
import os
from dataclasses import dataclass

from datetime import datetime
from unittest.mock import patch

import pytest
import pytz
from django.http import HttpResponse

from django.test import Client

from unittest import TestCase

from ocpi22.locations.serializers import LocationSerializer221
from ocpi22.models.credentials import Credentials
from ocpi22.models.location import Location, Evse
from ocpi22.models.tariff import Tariff
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.headers import make_headers
from ocpi22.tests.factories import (
    EvseFactory,
    LocationFactory,
    TariffFactory,
    CredentialsRoleFactory,
)
from ocpiconnector.party import Party
from util import reverse

faketime = datetime(2022, 1, 1, 12, 0, tzinfo=pytz.utc)
client = Client()
dirname = os.path.dirname(os.path.abspath(__file__))


def load_json(filename, serializer, object_type):
    with open(filename) as fp:
        data = json.load(fp)
        uid = data.get("id") or data.get("uid")
        instance = object_type.get_if_exists(uid=uid.upper()) if uid else None
        return serializer(data=data, instance=instance)


class TestLocations(TestCase):
    @pytest.mark.django_db
    def test_serialization_of_ocpi_specification_example(self):
        get_credentialsrole.cache_clear()
        serializer = load_json(
            "ocpi22/data/examples/location_example_parking_garage_opening_hours.json",
            LocationSerializer221,
            Location,
        )
        if serializer.is_valid():
            serializer.save()


@pytest.mark.django_db
def test_pre_save_always_saves_emi3_standard_evse_id():
    location = LocationFactory()
    evse = EvseFactory(evse_id="WHATEVER", location=location)
    assert (
        evse.evse_id
        == f"{location.ocpi_master.country_code}*{location.ocpi_master.party_id}*E{evse.uid}"
    )


@pytest.mark.django_db
class TestPublicAndNonPublicLocations:
    mock_send_all_updates_name = "ocpi22.ocpi.util.OcpiModule.send_all_updates"

    def test_that_exclusive_location_is_not_pushed(self):
        with patch(self.mock_send_all_updates_name) as mock_send_all_updates:
            location = LocationFactory(publish=False)
            location.send_updates()

        assert mock_send_all_updates.called is False

    def test_that_public_location_is_pushed(self):
        with patch(self.mock_send_all_updates_name) as mock_send_all_updates:
            location = LocationFactory(publish=True)
            location.send_updates()

        assert mock_send_all_updates.called

    @staticmethod
    def get_location_list(credentials: Credentials):
        return client.get(
            reverse("location-list"),
            headers=make_headers(
                credentials.ours_base64(),
                to=Party("FI", "CPO"),
                sender=Party("FI", "MSP"),
            ),
        )

    def test_that_exclusive_location_is_not_listed_in_locations_list(
        self, exclusive_location, msp_credentials_with_endpoints
    ):
        response = self.get_location_list(msp_credentials_with_endpoints)
        assert not any(
            location.get("id") == exclusive_location.uid
            for location in response.data.get("data")
        ), "A private location should not be listed when GETting the OCPI Locations list"

    def test_that_public_location_is_listed_in_locations_list(
        self, public_location, exclusive_location, msp_credentials_with_endpoints
    ):
        response = self.get_location_list(msp_credentials_with_endpoints)
        assert any(
            location.get("id") == public_location.uid
            for location in response.data.get("data")
        ), "A public location should be listed when GETting the OCPI Locations list"

    def test_location_list_view_only_returns_allowed_locations(
        self, msp_credentials_with_endpoints
    ):
        helsinki = LocationFactory(publish=True, uid="HELSINKI-ALLOWED")
        vantaa = LocationFactory(publish=True, uid="VANTAA-ALLOWED")
        kuopio_not_allowed = LocationFactory(publish=True, uid="KUOPIO-NOT-ALLOWED")
        msp_credentials_with_endpoints.allowed_locations.extend(
            [helsinki.uid, vantaa.uid]
        )
        msp_credentials_with_endpoints.save()
        response = self.get_location_list(msp_credentials_with_endpoints)
        response_data = response.json()["data"]
        location_ids = {location.get("id") for location in response_data}
        assert helsinki.uid in location_ids
        assert vantaa.uid in location_ids
        assert kuopio_not_allowed.uid not in location_ids

    def test_location_list_view_returns_everything_if_allowed_locations_empty_list(
        self, msp_credentials_with_endpoints
    ):
        iso_omena = LocationFactory(publish=True, uid="ISO-OMENA")
        itis = LocationFactory(publish=True, uid="ITIS")
        msp_credentials_with_endpoints.allowed_locations = []
        msp_credentials_with_endpoints.save()
        response = self.get_location_list(msp_credentials_with_endpoints)
        response_data = response.json()["data"]
        location_ids = {location.get("id") for location in response_data}
        assert iso_omena.uid in location_ids
        assert itis.uid in location_ids


@pytest.mark.django_db
def test_location_put_when_uid_does_not_match_between_url_parameters_and_body_data_fails(
    super_user_client,
):
    serializer = LocationSerializer221(instance=LocationFactory())
    response = super_user_client.put(
        reverse("location-by-id", args=["2.2.1", "FI", "CPO", "wrong-uid"]),
        data=serializer.data,
        format="json",
    )
    assert response.status_code == 400
    assert (
        "Location ID in URL does not match Location ID in payload"
        in response.data.get("status_message")
    )


@pytest.mark.django_db
class TestEvseMove:
    @dataclass
    class DataLoadResult:
        response: HttpResponse
        location: Location
        evses: list[Evse]

    def load_and_send_location_and_evse_data(
        self, _client, credentialsrole, filename: str
    ) -> DataLoadResult:
        with open(filename) as fp:
            data = json.load(fp)

        for evse in data.get("evses", []):
            for connector in evse.get("connectors"):
                for tariff_id in connector.get("tariff_ids"):
                    if not Tariff.objects.filter(uid=tariff_id).exists():
                        TariffFactory(uid=tariff_id, ocpi_master=credentialsrole)

        response = _client.put(
            reverse("location-by-id", args=["2.2.1", "FI", "CPO", data.get("id")]),
            data,
            format="json",
        )
        location = Location.objects.get(uid=data.get("id").upper())
        evses = [
            Evse.objects.get(uid=evse.get("uid").upper())
            for evse in data.get("evses", [])
        ]
        return self.DataLoadResult(response, location, evses)

    @pytest.mark.django_db
    def test_moving_an_evse_to_a_new_location_succeeds(self, super_user_client):
        result = self.load_and_send_location_and_evse_data(
            super_user_client,
            CredentialsRoleFactory(country_code="FI", party_id="CPO"),
            "ocpi22/data/examples/location_example.json",
        )
        assert result.response.status_code == 201
        assert result.evses[0].location.uid == result.location.uid

        result = self.load_and_send_location_and_evse_data(
            super_user_client,
            CredentialsRoleFactory(country_code="FI", party_id="CPO"),
            "ocpi22/data/examples/location_example_moved_evse.json",
        )
        assert result.response.status_code == 201
        assert result.evses[0].location.uid == result.location.uid

    @pytest.mark.django_db
    def test_adding_an_evse_to_an_existing_location_succeeds(self, super_user_client):
        result = self.load_and_send_location_and_evse_data(
            super_user_client,
            CredentialsRoleFactory(country_code="FI", party_id="CPO"),
            "ocpi22/data/examples/location_example.json",
        )
        assert result.response.status_code == 201
        assert result.evses[0].location.uid == result.location.uid

        result = self.load_and_send_location_and_evse_data(
            super_user_client,
            CredentialsRoleFactory(country_code="FI", party_id="CPO"),
            "ocpi22/data/examples/location_example_added_evse.json",
        )
        assert result.response.status_code == 200
        assert list(result.location.evses.values_list("uid", flat=True)) == [
            "3256",
            "3257",
            "3299",
        ]

    @pytest.mark.django_db
    def test_adding_a_connector_to_an_existing_location_and_evse_succeeds(
        self, super_user_client
    ):
        result = self.load_and_send_location_and_evse_data(
            super_user_client,
            CredentialsRoleFactory(country_code="FI", party_id="CPO"),
            "ocpi22/data/examples/location_example.json",
        )
        assert result.response.status_code == 201
        assert result.evses[0].location.uid == result.location.uid

        result = self.load_and_send_location_and_evse_data(
            super_user_client,
            CredentialsRoleFactory(country_code="FI", party_id="CPO"),
            "ocpi22/data/examples/location_example_added_connector.json",
        )
        assert result.response.status_code == 200
        connectors = result.location.evses.get(uid="3257").connectors.all()
        assert list(connectors.values_list("uid", flat=True)) == ["1", "2"]

    @pytest.mark.django_db
    def test_moving_an_evse_to_an_existing_location_succeeds(self, super_user_client):
        result = self.load_and_send_location_and_evse_data(
            super_user_client,
            CredentialsRoleFactory(country_code="FI", party_id="CPO"),
            "ocpi22/data/examples/location_example.json",
        )
        assert result.response.status_code == 201
        assert result.evses[0].location.uid == result.location.uid

        result = self.load_and_send_location_and_evse_data(
            super_user_client,
            CredentialsRoleFactory(country_code="FI", party_id="CPO"),
            "ocpi22/data/examples/location_example_loc2_empty.json",
        )
        assert result.response.status_code == 201

        result = self.load_and_send_location_and_evse_data(
            super_user_client,
            CredentialsRoleFactory(country_code="FI", party_id="CPO"),
            "ocpi22/data/examples/location_example_moved_evse.json",
        )
        assert result.response.status_code == 200
        assert result.evses[0].location.uid == result.location.uid

    @pytest.mark.django_db
    def test_updating_an_evse_and_connector_while_moving_them_to_a_new_location(
        self, super_user_client
    ):
        result = self.load_and_send_location_and_evse_data(
            super_user_client,
            CredentialsRoleFactory(country_code="FI", party_id="CPO"),
            "ocpi22/data/examples/location_example.json",
        )
        assert result.response.status_code == 201
        assert Evse.objects.get(uid=result.evses[0].uid).location == result.location
        assert result.evses[0].status == "AVAILABLE"
        assert result.evses[0].connectors.first().power_type == "AC_3_PHASE"

        result = self.load_and_send_location_and_evse_data(
            super_user_client,
            CredentialsRoleFactory(country_code="FI", party_id="CPO"),
            "ocpi22/data/examples/location_example_moved_and_changed_evse.json",
        )
        assert result.response.status_code == 201
        assert Evse.objects.get(uid=result.evses[0].uid).location == result.location
        assert result.evses[0].status == "CHARGING"
        assert result.evses[0].connectors.first().power_type == "AC_1_PHASE"
