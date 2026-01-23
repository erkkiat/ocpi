import pytest

from ocpi22.cpo.repositories import EvseRepository
from ocpi22.choices import OcpiRolesEnum
from ocpi22.tests.factories import CredentialsRoleFactory, LocationFactory, EvseFactory


class TestEvseRepository:
    @pytest.mark.django_db
    def test_iterate_status_by_credentials_returns_evse_statuses(
        self, hubject_credentials
    ):
        credentials_role = CredentialsRoleFactory(
            country_code="DE", party_id="ABC", role=OcpiRolesEnum.HUB.value
        )

        EvseFactory(
            uid="EVSE1",
            status="AVAILABLE",
            location=LocationFactory(ocpi_master=credentials_role),
        )
        EvseFactory(
            uid="EVSE2",
            status="CHARGING",
            location=LocationFactory(ocpi_master=credentials_role),
        )

        results = list(EvseRepository.iterate_status_by_credentials(credentials_role))
        assert results == [
            ("DE*ABC*EEVSE1", "AVAILABLE"),
            ("DE*ABC*EEVSE2", "CHARGING"),
        ]

    @pytest.mark.django_db
    def test_iterate_status_by_credentials_no_hubject_role_returns_empty_list(self):
        results = list(EvseRepository.iterate_status_by_credentials("dummy_role"))
        assert results == []

    @pytest.mark.django_db
    def test_iterate_status_by_credentials_with_allowed_locations(
        self, hubject_credentials
    ):
        hubject_credentials.allowed_locations = ["LOC1"]
        hubject_credentials.save()

        credentials_role = CredentialsRoleFactory(
            country_code="DE",
            party_id="ABC",
            role=OcpiRolesEnum.HUB.value,
        )

        EvseFactory(
            uid="EVSE1",
            status="AVAILABLE",
            location=LocationFactory(uid="LOC1", ocpi_master=credentials_role),
        )
        EvseFactory(
            uid="EVSE2",
            status="CHARGING",
            location=LocationFactory(uid="LOC2", ocpi_master=credentials_role),
        )

        results = list(EvseRepository.iterate_status_by_credentials(credentials_role))
        assert results == [("DE*ABC*EEVSE1", "AVAILABLE")]
