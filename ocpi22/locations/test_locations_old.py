import json
import os

from datetime import datetime

import pytest
import pytz

from django.test import Client

from unittest import TestCase

from icecream import ic

from ocpi22.locations.serializers import LocationSerializer221
from ocpi22.tests.factories import EvseFactory, LocationFactory
from ocpiconnector.testutil import OCPIAPIRequestFactory

faketime = datetime(2022, 1, 1, 12, 0, tzinfo=pytz.utc)
client = Client()
dirname = os.path.dirname(os.path.abspath(__file__))
api_factory = OCPIAPIRequestFactory()


def load_json(filename, serializer):
    with open(filename) as fp:
        data = json.load(fp)
        return serializer(data).data


class TestLocations(TestCase):
    def test_serialization(self):
        location = load_json(
            "ocpi22/data/examples/location_example_parking_garage_opening_hours.json",
            LocationSerializer221,
        )
        ic(location)


@pytest.mark.django_db
def test_pre_save_always_saves_emi3_standard_evse_id(self):
    location = LocationFactory()
    evse = EvseFactory(evse_id="WHATEVER", location=location)
    assert (
        evse.evse_id
        == f"{location.ocpi_master.country_code}*{location.ocpi_master.party_id}*E{evse.uid}"
    )
