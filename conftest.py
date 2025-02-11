import pytest
from rest_framework.test import APIClient

from ocpi22.choices import OcpiModuleEnum, EndpointRoleEnum
from test_util import cleanup_credentialsrole

from ocpi22.tests.factories import (
    CredentialsFactory,
    BusinessDetailsFactory,
    CredentialsRoleFactory,
    EndpointFactory,
)
from ocpiconnector.party import Party


@pytest.fixture
def client():
    client = APIClient()
    client.credentials()
    return client


@pytest.fixture
def msp_credentials_with_endpoints():
    cleanup_credentialsrole(Party("FI", "MSP"))

    credentials = CredentialsFactory()
    business_details = BusinessDetailsFactory(name="Test MSP")
    CredentialsRoleFactory(
        credentials=credentials,
        role="EMSP",
        country_code="FI",
        party_id="MSP",
        business_details=business_details,
    )

    [
        EndpointFactory(
            credentials=credentials,
            identifier=identifier.value,
            role=role,
            url=f"https://example.com/ocpi/{identifier.value.lower()}",
        )
        for identifier, role in (
            (OcpiModuleEnum.CDRS, EndpointRoleEnum.RECEIVER),
            (OcpiModuleEnum.SESSIONS, EndpointRoleEnum.RECEIVER)
        )
    ]

    return credentials


@pytest.fixture
def default_credentials():
    credentials = CredentialsFactory()
    CredentialsRoleFactory(credentials=credentials)

    EndpointFactory(
        credentials=credentials,
        identifier=OcpiModuleEnum.CDRS.value,
        role=EndpointRoleEnum.RECEIVER,
        url="https://example.com/ocpi/cdrs",
    )

    return credentials


@pytest.fixture(autouse=True)
def enable_db_access_for_doctests(request, django_db_blocker):
    """Allow database access for doctests only."""
    if request.node.getparent(pytest.DoctestItem):
        django_db_blocker.unblock()
