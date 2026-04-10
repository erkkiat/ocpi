from base64 import b64encode

import pytest
from asgiref.sync import sync_to_async
from django.conf import settings
from rest_framework.test import APIClient

from ocpi22.choices import OcpiModuleEnum, EndpointRoleEnum, OcpiRolesEnum
from ocpi22.models.credentials import Credentials
from ocpi22.ocpi.auth import get_credentialsrole
from ocpiconnector.ocpi_identities import get_our_credentialsrole
from test_util import cleanup_credentialsrole

from ocpi22.tests.factories import (
    CredentialsFactory,
    BusinessDetailsFactory,
    CredentialsRoleFactory,
    EndpointFactory,
    UserFactory,
    SuperUserFactory,
    StaffUserFactory,
)
from ocpiconnector.party import Party
from integrations.hubject.services import HubjectService


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
    credentials = b64encode(
        f"{authenticated_user.username}:j0s9J117uS126dNr915zIj7d1J10UJ2f".encode()
    ).decode("utf-8")
    auth_headers = {"HTTP_AUTHORIZATION": f"Basic {credentials}"}
    client.defaults.update(auth_headers)
    return client


@pytest.fixture
def admin_user_client(db, admin_user):
    client = APIClient()
    credentials = b64encode(
        f"{admin_user.username}:j0s9J117uS126dNr915zIj7d1J10UJ2f".encode()
    ).decode("utf-8")
    auth_headers = {"HTTP_AUTHORIZATION": f"Basic {credentials}"}
    client.defaults.update(auth_headers)
    return client


@pytest.fixture
def super_user_client(db, super_user):
    client = APIClient()
    credentials = b64encode(
        f"{super_user.username}:j0s9J117uS126dNr915zIj7d1J10UJ2f".encode()
    ).decode("utf-8")
    auth_headers = {"HTTP_AUTHORIZATION": f"Basic {credentials}"}
    client.defaults.update(auth_headers)
    return client


@pytest.fixture
def msp_credentials_with_endpoints():
    cleanup_credentialsrole(Party("FI", "MSP"))

    credentials = CredentialsFactory(theirs="ABC", ours="DEF")
    business_details = BusinessDetailsFactory(name="Test MSP")
    credentialsrole = CredentialsRoleFactory(
        role="EMSP",
        country_code="FI",
        party_id="MSP",
        business_details=business_details,
        credentials=credentials,
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
            (OcpiModuleEnum.SESSIONS, EndpointRoleEnum.RECEIVER),
        )
    ]

    return credentialsrole.credentials


@pytest.fixture
def default_credentials():
    credentials = CredentialsFactory()
    CredentialsRoleFactory(credentials=credentials)

    EndpointFactory(
        credentials=credentials,
        identifier=OcpiModuleEnum.CDRS.value,
        role=EndpointRoleEnum.RECEIVER,
        url="https://localhost/ocpi/cdrs",
    )

    return credentials


@pytest.fixture(autouse=True)
def enable_db_access_for_doctests(request, django_db_blocker):
    """Allow database access for doctests only."""
    if request.node.getparent(pytest.DoctestItem):
        django_db_blocker.unblock()


@pytest.fixture
def hubject_credentials() -> Credentials:
    get_our_credentialsrole.cache_clear()
    get_credentialsrole.cache_clear()
    party = Party.from_str(settings.HUBJECT_OPERATOR_ID)

    credentials = CredentialsFactory(
        auth_priority=2,
        url="https://hubjectfixture.com/ocpi/hubject",
    )

    return CredentialsRoleFactory(
        country_code=party.country_code,
        party_id=party.party_id,
        role="HUB",
        business_details__name="Hubject",
        credentials=credentials,
    ).credentials


@pytest.fixture
async def hubject_credentials_async():
    HubjectService._get_hubject_credentials_id.cache_clear()
    creds_role = await sync_to_async(CredentialsRoleFactory)(
        country_code="DE",
        party_id="ICE",
        role=OcpiRolesEnum.HUB.value,
        business_details__name="Hubject",
        credentials__auth_priority=2,
    )
    yield creds_role
    await sync_to_async(creds_role.credentials.delete)()


@pytest.fixture
def clear_hubject_credentials_role():
    from ocpi22.ocpi.auth import find_credentials
    from ocpi22.choices import OcpiRolesEnum
    from ocpi22.models.credentials import CredentialsRole

    HubjectService._get_hubject_credentials_id.cache_clear()
    get_our_credentialsrole.cache_clear()
    get_credentialsrole.cache_clear()
    find_credentials.cache_clear()

    country_code, party_id = settings.HUBJECT_OPERATOR_ID.split("*", 1)

    roles = CredentialsRole.objects.filter(
        country_code=country_code, party_id=party_id, role=OcpiRolesEnum.HUB
    )

    for role in roles:
        if role.credentials:
            role.credentials.delete()
        role.delete()
