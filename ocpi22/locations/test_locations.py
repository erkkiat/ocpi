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

from ocpi22.locations.serializers import LocationSerializer221, EvseSerializer
from unittest.mock import ANY
from ocpi22.models.credentials import Credentials
from ocpi22.models.location import Location, Evse
from ocpi22.models.tariff import Tariff
from ocpi22.ocpi.auth import get_credentialsrole, find_credentials
from ocpi22.ocpi.headers import make_headers
from ocpi22.test_tariff_location_and_evse import load_example
from ocpi22.tests.factories import (
    EvseFactory,
    LocationFactory,
    TariffFactory,
    CredentialsRoleFactory,
    BusinessDetailsFactory,
    SolidTariffFactory,
)
from ocpiconnector.party import Party
from util import reverse

from ocpiconnector.ocpi_identities import (
    get_our_credentialsrole,
)

from ocpi22.credentials.util import find_endpoints_by_roles


faketime = datetime(2022, 1, 1, 12, 0, tzinfo=pytz.utc)
client = Client()
dirname = os.path.dirname(os.path.abspath(__file__))


def load_json(filename, serializer, object_type):
    with open(filename) as fp:
        data = json.load(fp)
        uid = data.get("id") or data.get("uid")
        instance = object_type.get_if_exists(uid=uid.upper()) if uid else None
        return serializer(data=data, instance=instance)


@pytest.fixture
def msp_de_ice():
    return CredentialsRoleFactory(country_code="DE", party_id="ICE", role="EMSP")


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
def test_evse_serializer_includes_physical_reference():
    evse = EvseFactory(physical_reference="A1")
    data = EvseSerializer(evse, context={"request": None}).data
    assert "physical_reference" in data
    assert data["physical_reference"] == "A1"


@pytest.mark.django_db
def test_evse_serializer_physical_reference_is_none_when_not_set():
    evse = EvseFactory(physical_reference=None)
    data = EvseSerializer(evse, context={"request": None}).data
    assert data["physical_reference"] is None


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
        find_credentials.cache_clear()

        helsinki = LocationFactory(publish=True, uid="HELSINKI-ALLOWED")
        vantaa = LocationFactory(publish=True, uid="VANTAA-ALLOWED")
        kuopio_not_allowed = LocationFactory(publish=True, uid="KUOPIO-NOT-ALLOWED")

        msp_credentials_with_endpoints.allowed_locations = [helsinki.uid, vantaa.uid]
        msp_credentials_with_endpoints.save()
        msp_credentials_with_endpoints.refresh_from_db()

        response = self.get_location_list(msp_credentials_with_endpoints)
        response_data = response.json()["data"]
        location_ids = {location.get("id") for location in response_data}

        assert helsinki.uid in location_ids
        assert vantaa.uid in location_ids
        assert kuopio_not_allowed.uid not in location_ids

    def test_location_list_view_returns_everything_if_allowed_locations_empty_list(
        self, msp_credentials_with_endpoints
    ):
        find_credentials.cache_clear()

        iso_omena = LocationFactory(publish=True, uid="ISO-OMENA")
        itis = LocationFactory(publish=True, uid="ITIS")

        msp_credentials_with_endpoints.allowed_locations = []
        msp_credentials_with_endpoints.save()
        msp_credentials_with_endpoints.refresh_from_db()

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
        assert sorted(list(result.location.evses.values_list("uid", flat=True))) == [
            "3256",
            "3257",
            "3299",
        ]

    @pytest.mark.django_db
    def test_adding_a_connector_to_an_existing_location_and_evse_succeeds(
        self, super_user_client
    ):
        role = CredentialsRoleFactory(country_code="FI", party_id="CPO")
        result = self.load_and_send_location_and_evse_data(
            super_user_client,
            role,
            "ocpi22/data/examples/location_example.json",
        )
        assert result.response.status_code == 201
        assert result.evses[0].location.uid == result.location.uid

        result = self.load_and_send_location_and_evse_data(
            super_user_client,
            role,
            "ocpi22/data/examples/location_example_added_connector.json",
        )
        assert result.response.status_code == 200
        connectors = result.location.evses.get(uid="3257").connectors.all()
        assert set(connectors.values_list("uid", flat=True)) == {"1", "2"}

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


@pytest.fixture
def roaming_enabled_prague():
    return LocationFactory(
        uid="PRAGUE",
        publish=True,
        roaming_enabled=True,
    )


@pytest.fixture
def roaming_disabled_paris():
    return LocationFactory(
        uid="PARIS",
        publish=True,
        roaming_enabled=False,
    )


@pytest.fixture
def roaming_enabled_kuopio():
    return LocationFactory(
        uid="KUOPIO",
        publish=True,
        roaming_enabled=True,
    )


@pytest.fixture
def nsp_lk_nsp():
    return CredentialsRoleFactory.create(
        country_code="LK",
        party_id="NSP",
        role="NSP",
        business_details=BusinessDetailsFactory(name="Test NSP"),
    )


@pytest.fixture
def nap_np_nap():
    return CredentialsRoleFactory(
        country_code="NP",
        party_id="NAP",
        role="NAP",
        business_details=BusinessDetailsFactory(name="Test NAP"),
    )


@pytest.fixture
def hub_fr_gir():
    return CredentialsRoleFactory(
        country_code="FR",
        party_id="GIR",
        role="HUB",
        business_details=BusinessDetailsFactory(name="Gireve"),
    )


@pytest.fixture
def ocpi_master():
    get_our_credentialsrole.cache_clear()
    get_credentialsrole.cache_clear()

    return CredentialsRoleFactory(country_code="FI", party_id="CPO")


@pytest.fixture
def location_data(ocpi_master):
    data = load_example("data/examples/location_example.json")
    data["country_code"] = ocpi_master.country_code
    data["party_id"] = ocpi_master.party_id

    return data


@pytest.fixture
def tariffs(ocpi_master):
    t11 = TariffFactory(uid="11", ocpi_master=ocpi_master)
    t12 = TariffFactory(uid="12", ocpi_master=ocpi_master)
    t13 = TariffFactory(uid="13", ocpi_master=ocpi_master)

    SolidTariffFactory(
        external_id="11", operator=ocpi_master, msp=None, ocpi_tariff=t11
    )
    SolidTariffFactory(
        external_id="12", operator=ocpi_master, msp=None, ocpi_tariff=t12
    )
    SolidTariffFactory(
        external_id="13", operator=ocpi_master, msp=None, ocpi_tariff=t13
    )


@pytest.mark.django_db
class TestRoamingEnabledLocations:
    @pytest.mark.parametrize(
        "role, expected_locations",
        [
            ("CPO", {"PRAGUE", "KUOPIO", "PARIS"}),
            ("HUB", {"PRAGUE", "KUOPIO"}),
            ("EMSP", {"PRAGUE", "KUOPIO"}),
            ("NSP", {"PRAGUE", "KUOPIO", "PARIS"}),
            ("NAP", {"PRAGUE", "KUOPIO", "PARIS"}),
        ],
    )
    def test_get_all_locations_per_role(
        self,
        authenticated_user_client,
        role,
        expected_locations,
        roaming_enabled_kuopio,
        roaming_enabled_prague,
        roaming_disabled_paris,
        ocpi_master,
        hub_fr_gir,
        nsp_lk_nsp,
        msp_de_ice,
        nap_np_nap,
    ):
        role_to_credentials = {
            "CPO": ocpi_master,
            "HUB": hub_fr_gir,
            "NSP": nsp_lk_nsp,
            "EMSP": msp_de_ice,
            "NAP": nap_np_nap,
        }
        credentials_role = role_to_credentials[role]

        response = authenticated_user_client.get(
            reverse("location-list"),
            headers=make_headers(
                credentials_role.credentials.ours_base64(),
                to=Party("FI", "CPO"),
                sender=Party(credentials_role.country_code, credentials_role.party_id),
            ),
        )

        location_ids = {location.get("id") for location in response.json().get("data")}

        assert response.status_code == 200
        assert location_ids == expected_locations

    @pytest.mark.parametrize(
        "roaming_enabled, expected_status, expected_response",
        [
            (True, 201, {"roaming_enabled": True}),
            (False, 201, {"roaming_enabled": False}),
            (None, 201, {"roaming_enabled": True}),
        ],
    )
    @patch("ocpi22.ocpi.util.OcpiModule.send_background_update")
    def test_put_location_with_roaming_enabled(
        self,
        mock_send_background_update,
        authenticated_user_client,
        location_data,
        tariffs,
        roaming_enabled,
        expected_status,
        expected_response,
        ocpi_master,
        nsp_lk_nsp,
        hub_fr_gir,
        msp_de_ice,
        nap_np_nap,
    ):
        find_endpoints_by_roles.cache_clear()
        url = reverse("cpo:update_location")

        if roaming_enabled is not None:
            location_data["roaming_enabled"] = roaming_enabled

        response = authenticated_user_client.put(url, location_data, format="json")

        assert response.status_code == expected_status
        assert (
            response.json()["roaming_enabled"] == expected_response["roaming_enabled"]
            if roaming_enabled is not None
            else expected_response
        )

        roaming_enabled = response.json()["roaming_enabled"]
        roles_to_check = [nsp_lk_nsp, nap_np_nap]

        if roaming_enabled:
            roles_to_check.extend([hub_fr_gir, msp_de_ice])

        for role in roles_to_check:
            party = Party(role.country_code, role.party_id)
            mock_send_background_update.assert_any_call(
                ANY, ANY, ANY, to=party, sender=ANY, method=ANY, credentials=ANY
            )

        roles_not_to_check = (
            [] if roaming_enabled else [hub_fr_gir, msp_de_ice, ocpi_master]
        )

        for role in roles_not_to_check:
            party = Party(role.country_code, role.party_id)
            for call in mock_send_background_update.call_args_list:
                args, _ = call
                kwargs = call.kwargs
                assert (
                    kwargs["to"] != party
                ), f"Role {role.role} should not have been notified"
