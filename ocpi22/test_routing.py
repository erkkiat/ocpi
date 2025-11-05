import pytest

from ocpi22.choices import OcpiModuleEnum
from ocpi22.routing import find_route_from_credentials, Route
from ocpi22.tests.factories import (
    CredentialsRoleFactoryWithoutCredentials,
    CredentialsFactory,
)


@pytest.mark.django_db
def test_routing_through_ocpi_succeeds(ocpi_master):
    route = find_route_from_credentials(
        ocpi_master.credentials, OcpiModuleEnum.SESSIONS
    )
    assert isinstance(route, Route)
    assert route.credentials_id == ocpi_master.credentials.pk
    assert route.route_through_oicp is False
    assert route.identifier == OcpiModuleEnum.SESSIONS


@pytest.mark.django_db
def test_routing_through_oicp_succeeds(hubject_credentials):
    route = find_route_from_credentials(hubject_credentials, OcpiModuleEnum.SESSIONS)
    assert isinstance(route, Route)
    assert route.credentials_id == hubject_credentials.pk
    assert route.route_through_oicp is True


@pytest.mark.django_db
def test_routing_raises_value_error_when_no_endpoints(monkeypatch):
    # Not using CredentialsRoleFactory to avoid creating any Endpoints
    credentials = CredentialsFactory()
    CredentialsRoleFactoryWithoutCredentials(
        country_code="FI", party_id="CPO", role="CPO", credentials=credentials
    )

    with pytest.raises(ValueError) as exc:
        find_route_from_credentials(
            credentials, OcpiModuleEnum.SESSIONS, role="RECEIVER"
        )
    assert (
        f"Endpoint `{OcpiModuleEnum.SESSIONS.value}` RECEIVER not found for party"
        in str(exc.value)
    )
