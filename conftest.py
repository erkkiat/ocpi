import pytest
from rest_framework.test import APIClient

from ocpi22.choices import OcpiModuleEnum, EndpointRoleEnum

from ocpi22.tests.factories import (
    CredentialsFactory,
    BusinessDetailsFactory,
    CredentialsRoleFactory,
    EndpointFactory,
    UserFactory,
    SuperUserFactory,
    StaffUserFactory,
)


@pytest.fixture
def client():
    client = APIClient()
    client.credentials()
    return client


@pytest.fixture
def super_user():
    return SuperUserFactory()


@pytest.fixture
def authenticated_user():
    return UserFactory()


@pytest.fixture
def admin_user():
    return StaffUserFactory()


@pytest.fixture
def authenticated_user_client(db, authenticated_user):
    client = APIClient()
    client.force_authenticate(user=authenticated_user)
    return client


@pytest.fixture
def admin_user_client(db, admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def super_user_client(db, super_user):
    client = APIClient()
    client.force_authenticate(user=super_user)
    return client


@pytest.fixture
def cdr_receiver_credentials():
    credentials = CredentialsFactory()
    business_details = BusinessDetailsFactory(name="Test MSP")
    CredentialsRoleFactory(
        credentials=credentials,
        role="EMSP",
        country_code="FI",
        party_id="MSP",
        business_details=business_details,
    )

    EndpointFactory(
        credentials=credentials,
        identifier=OcpiModuleEnum.CDRS.value,
        role=EndpointRoleEnum.RECEIVER,
        url="https://example.com/ocpi/cdrs",
    )

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
