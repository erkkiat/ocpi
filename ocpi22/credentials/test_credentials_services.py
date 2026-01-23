import pytest
from ocpi22.credentials.services import CredentialsService
from ocpi22.tests.factories import (
    CredentialsFactory,
    LocationFactory,
    EvseFactory,
    CredentialsRoleFactory,
)


@pytest.mark.django_db
class TestCredentialsService:
    def test_is_location_allowed_by_default(self):
        credentials = CredentialsFactory(allowed_locations=[])
        assert CredentialsService.is_location_allowed(credentials, "LOC1")

    def test_is_location_allowed_valid(self):
        credentials = CredentialsFactory(allowed_locations=["LOC1", "LOC2"])
        assert CredentialsService.is_location_allowed(credentials, "LOC2")

    def test_is_location_allowed_invalid(self):
        credentials = CredentialsFactory(allowed_locations=["LOC1", "LOC2"])
        assert not CredentialsService.is_location_allowed(credentials, "LOC3")

    def test_is_evse_allowed_for_credentials_no_allowed_locations(self):
        credentials = CredentialsFactory(allowed_locations=[])
        evse = EvseFactory()
        assert CredentialsService.is_evse_allowed(credentials, evse)

    def test_is_evse_allowed_for_credentials_valid(self):
        role = CredentialsRoleFactory()
        location = LocationFactory(uid="LOC1", ocpi_master=role)
        evse = EvseFactory(location=location)

        role.credentials.allowed_locations = ["LOC1", "LOC2"]
        role.credentials.save()

        assert CredentialsService.is_evse_allowed(role.credentials, evse)

    def test_is_evse_allowed_for_credentials_invalid(self):
        location = LocationFactory(uid="LOC3")
        evse = EvseFactory(location=location)
        credentials = CredentialsFactory(allowed_locations=["LOC1", "LOC2"])

        assert not CredentialsService.is_evse_allowed(credentials, evse)
