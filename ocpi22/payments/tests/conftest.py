import pytest

from ocpi22.choices import OcpiRolesEnum
from ocpi22.tests.factories import (
    CredentialsRoleFactory,
    TerminalFactory,
    FinancialAdviceConfirmationFactory,
)


@pytest.fixture
def credentialsrole(db):
    return CredentialsRoleFactory(
        role=OcpiRolesEnum.PTP,
        party_id="PAY",
        country_code="NL",
    )


@pytest.fixture
def credentials(credentialsrole):
    return credentialsrole.credentials


@pytest.fixture
def db_terminal(credentialsrole):
    def _create_terminal(**kwargs):
        kwargs.setdefault("credentials", credentialsrole.credentials)
        return TerminalFactory(**kwargs)

    return _create_terminal


@pytest.fixture
def db_fac(credentialsrole):
    def _create_fac(**kwargs):
        kwargs.setdefault("credentials", credentialsrole.credentials)
        return FinancialAdviceConfirmationFactory(**kwargs)

    return _create_fac
