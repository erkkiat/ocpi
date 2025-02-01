import pytest
from rest_framework.test import APIClient

from ocpi22.choices import OcpiModuleEnum, EndpointRoleEnum

from ocpi22.tests.factories import (
    CredentialsFactory,
    BusinessDetailsFactory,
    CredentialsRoleFactory,
    EndpointFactory,
)


@pytest.fixture
def client():
    client = APIClient()
    client.credentials()
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
