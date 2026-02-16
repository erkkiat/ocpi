"""
Pytest fixtures for DirectPayment module tests
"""

import pytest

from ocpi22.models.credentials import Credentials, CredentialsRole
from ocpi22.models.business_details import BusinessDetails
from ocpi22.payments.models import Terminal, FinancialAdviceConfirmation
from ocpi22.choices import OcpiRolesEnum


@pytest.fixture
def credentials(db):
    """Create test PTP credentials."""
    creds = Credentials.objects.create(
        url="https://ptp.example.com/ocpi/2.2.1/",
    )
    business_details = BusinessDetails.objects.create(
        name="Test Payment Terminal Provider",
        website="https://ptp.example.com",
    )
    CredentialsRole.objects.create(
        credentials=creds,
        party_id="PTP",
        country_code="NL",
        role=OcpiRolesEnum.PTP,
        business_details=business_details,
    )
    return creds


@pytest.fixture
def db_terminal(db, credentials):
    """Factory fixture for creating Terminal instances."""

    def _create_terminal(**kwargs):
        if "credentials" not in kwargs:
            kwargs["credentials"] = credentials

        location_ids = kwargs.pop("location_ids", None)
        evse_uids = kwargs.pop("evse_uids", None)

        terminal = Terminal.objects.create(**kwargs)

        if location_ids is not None:
            pass

        if evse_uids is not None:
            pass

        return terminal

    return _create_terminal


@pytest.fixture
def db_fac(db, credentials):
    """Factory fixture for creating FAC instances."""

    def _create_fac(**kwargs):
        if "credentials" not in kwargs:
            kwargs["credentials"] = credentials

        return FinancialAdviceConfirmation.objects.create(**kwargs)

    return _create_fac
