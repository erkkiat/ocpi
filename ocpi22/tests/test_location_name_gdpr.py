import csv
import os

import pytest
from django.apps import apps

from ocpi22.locations.serializers import LocationSerializer221
from ocpi22.models.location import Location
from ocpi22.test_tariff_location_and_evse import load_example
from ocpi22.ocpi.auth import get_credentialsrole


@pytest.fixture
def location_example():
    data = load_example("data/examples/location_example.json")
    data["evses"] = []
    return data


def test_assert_that_pytorch_env_vars_set_correctly():
    assert os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "1"


def test_location_name_updates_to_street_address_when_using_a_person_name(
    admin_user_client, location_example
):
    app_path = apps.get_app_config("ocpi22").path
    csv_path = os.path.join(app_path, "data", "fictional_names.csv")
    with open(csv_path) as file:
        data = csv.reader(file)
        next(data)  # Skip the header row
        for uid, name, street in data:
            uid = uid.strip()
            name = name.strip()
            street = street.strip()

            location_example["id"] = uid
            location_example["name"] = name
            location_example["address"] = street

            get_credentialsrole.cache_clear()
            serializer = LocationSerializer221(data=location_example)
            if serializer.is_valid():
                serializer.save()

            saved_location = Location.objects.get(uid=uid)
            assert saved_location.name == street
            assert saved_location.address == street


def test_location_name_does_not_update_to_street_address_when_using_a_location_name(
    admin_user_client, location_example
):
    location_example["id"] = "HELSINKI_SUPERCHARGER"
    location_example["name"] = "Helsinki Supercharger"
    location_example["address"] = "Pohjoisesplanadi 11"

    get_credentialsrole.cache_clear()
    serializer = LocationSerializer221(data=location_example)
    if serializer.is_valid():
        serializer.save()

    saved_location = Location.objects.get(uid="HELSINKI_SUPERCHARGER")
    assert saved_location.name == "Helsinki Supercharger"
    assert saved_location.address == "Pohjoisesplanadi 11"
