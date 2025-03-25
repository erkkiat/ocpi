import os

import pytest
from django.urls import reverse

from ocpi22.models.location import Location
from ocpi22.test_tariff_location_and_evse import load_example
from ocpi22.ocpi.auth import get_credentialsrole


@pytest.fixture
def location_example():
    data = load_example("data/examples/location_example.json")
    data["country_code"] = "FI"
    data["party_id"] = "CPO"
    data["evses"] = []
    return data


@pytest.fixture
def person_names():
    return [
        ("PAUL_MUELLER", "Paul Müller", "Kurfürstendamm 18"),
        ("SARAH_MARTIN", "Sarah Martin", "Rue de la République 19"),
        ("MANON_LEROY", "Manon Leroy", "Rue de la Paix 21"),
        ("MIGUEL_GOMEZ", "Miguel Gómez", "Calle de Alcalá 22"),
        ("LOTTE_SMITS", "Lotte Smits", "Singel 23"),
        ("EMMA_SCHNEIDER", "Emma Schneider", "Schillerstraße 24"),
        ("LUKAS_MUELLER", "Lukas Müller", "Wilhelmstraße 25"),
        ("CAMILLE_MARTIN", "Camille Martin", "Rue de la Paix 26"),
        ("SOFIA_MARTINEZ", "Sofía Martínez", "Calle de Serrano 28"),
        ("CAMILLE_MOREAU", "Camille Moreau", "Rue de la Paix 29"),
    ]


def test_assert_that_pytorch_env_vars_set_correctly():
    assert os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "1"


def test_location_name_updates_to_street_address_when_using_a_person_name(
    super_user_client, location_example, person_names
):
    for uid, name, street in person_names:
        get_credentialsrole.cache_clear()
        url = reverse("location-by-id", args=["2.2.1", "FI", "CPO", uid])

        location_example["id"] = uid
        location_example["name"] = name
        location_example["address"] = street

        res = super_user_client.put(url, location_example, format="json")
        assert res.status_code == 201

        saved_location = Location.objects.get(uid=uid)
        assert saved_location.name == street
        assert saved_location.address == street


def test_location_name_does_not_update_to_street_address_when_using_a_location_name(
    super_user_client, location_example
):
    location_example["id"] = "HELSINKI_SUPERCHARGER"
    location_example["name"] = "Helsinki Supercharger"
    location_example["address"] = "Pohjoisesplanadi 11"

    url = reverse(
        "location-by-id", args=["2.2.1", "FI", "CPO", "HELSINKI_SUPERCHARGER"]
    )

    res = super_user_client.put(url, location_example, format="json")
    assert res.status_code == 201

    saved_location = Location.objects.get(uid="HELSINKI_SUPERCHARGER")
    assert saved_location.name == "Helsinki Supercharger"
    assert saved_location.address == "Pohjoisesplanadi 11"
