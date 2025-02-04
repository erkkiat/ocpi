import json
import os

from datetime import datetime

import pytest
import pytz

from django.test import Client

from unittest import TestCase


from ocpi22.locations.serializers import LocationSerializer221
from ocpi22.models.location import Location
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.tests.factories import EvseFactory, LocationFactory

faketime = datetime(2022, 1, 1, 12, 0, tzinfo=pytz.utc)
client = Client()
dirname = os.path.dirname(os.path.abspath(__file__))


def load_json(filename, serializer, object_type):
    with open(filename) as fp:
        data = json.load(fp)
        uid = data.get('id') or data.get('uid')
        instance = object_type.get_if_exists(uid=uid.upper()) if uid else None
        return serializer(data=data, instance=instance)


class TestLocations(TestCase):
    @pytest.mark.django_db
    def test_serialization_of_ocpi_specification_example(self):
        get_credentialsrole.cache_clear()
        serializer = load_json(
            "ocpi22/data/examples/location_example_parking_garage_opening_hours.json",
            LocationSerializer221,
            Location
        )
        if serializer.is_valid():
            serializer.save()

    @pytest.mark.django_db
    def test_serialization_to_update_existing_location(self):
        get_credentialsrole.cache_clear()
        serializer = load_json(
            "ocpi22/data/examples/location_example_parking_garage_opening_hours.json",
            LocationSerializer221,
            Location
        )
        assert serializer.is_valid()
        location1 = serializer.save()

        serializer = load_json(
            "ocpi22/data/examples/location_example_parking_garage_opening_hours.json",
            LocationSerializer221,
            Location
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
