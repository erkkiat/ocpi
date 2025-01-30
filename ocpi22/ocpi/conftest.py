import pytest

from ocpi22.choices import OcpiModuleEnum, EndpointRoleEnum
from ocpi22.models.cdr import Cdr
from ocpi22.models.credentials import Credentials, CredentialsRole, Endpoint
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session
from ocpi22.models.tariff import Tariff
from ocpi22.models.token import Token
from ocpi22.tests.factories import (
    CredentialsFactory,
    CredentialsRoleFactory,
    EndpointFactory,
    BusinessDetailsFactory,
)


@pytest.fixture
def drop_all_data():
    Tariff.objects.all().delete()
    Session.objects.all().delete()
    Cdr.objects.all().delete()
    Connector.objects.all().delete()
    Evse.objects.all().delete()
    Location.objects.all().delete()
    Token.objects.all().delete()
    CredentialsRole.objects.all().delete()
    Endpoint.objects.all().delete()
    Credentials.objects.all().delete()


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
