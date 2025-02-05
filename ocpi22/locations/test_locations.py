import json
import os

from datetime import datetime
from unittest.mock import patch

import pytest
import pytz

from django.test import Client

from unittest import TestCase


from ocpi22.locations.serializers import LocationSerializer221
from ocpi22.models.credentials import Credentials
from ocpi22.models.location import Location
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.headers import make_headers
from ocpi22.tests.factories import EvseFactory, LocationFactory
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
    def test_serialization_to_update_existing_location(self):
        get_credentialsrole.cache_clear()
        serializer = load_json(
            "ocpi22/data/examples/location_example_parking_garage_opening_hours.json",
            LocationSerializer221,
            Location,
        )
        assert serializer.is_valid()
        location1 = serializer.save()

        serializer = load_json(
            "ocpi22/data/examples/location_example_parking_garage_opening_hours.json",
            LocationSerializer221,
            Location,
        )
        assert serializer.is_valid()
        location2 = serializer.save()

        assert location1.pk == location2.pk


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
    mocked_function_name = "ocpi22.ocpi.util.OcpiModule.send_all_updates"

    def test_that_exclusive_location_is_not_pushed(self):
        with patch(self.mocked_function_name) as mock_send:
            location = LocationFactory(publish=False)
            location.send_updates()

        assert mock_send.called is False

    def test_that_public_location_is_pushed(self):
        with patch(self.mocked_function_name) as mock_send:
            location = LocationFactory(publish=True)
            location.send_updates()

        assert mock_send.called is True

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
        self, exclusive_location, cdr_receiver_credentials
    ):
        response = self.get_location_list(cdr_receiver_credentials)
        assert not any(
            location.get("id") == exclusive_location.uid
            for location in response.data.get("data")
        ), "A private location should not be listed when GETting the OCPI Locations list"

    def test_that_public_location_is_listed_in_locations_list(
        self, public_location, exclusive_location, cdr_receiver_credentials
    ):
        response = self.get_location_list(cdr_receiver_credentials)
        assert any(
            location.get("id") == public_location.uid
            for location in response.data.get("data")
        ), "A public location should be listed when GETting the OCPI Locations list"
