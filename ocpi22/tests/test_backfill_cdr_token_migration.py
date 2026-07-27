import pytz
from datetime import datetime

import pytest
from django.core.management import call_command

from ocpi22.models.cdr import Cdr
from ocpi22.models.session import Session
from ocpi22.models.cdrlocation import CdrLocation
from ocpi22.tests.factories import (
    CdrTokenFactory,
    OCPISessionFactory,
    CredentialsRoleFactory,
)


pytestmark = [pytest.mark.django_db(transaction=True)]


@pytest.fixture
def cpo_credentialsrole():
    return CredentialsRoleFactory(role="CPO", country_code="FI", party_id="CPO")


@pytest.fixture
def emsp_credentialsrole():
    return CredentialsRoleFactory(role="EMSP", country_code="DE", party_id="ICE")


def _create_cdr(
    uid,
    ocpi_master,
    cdr_token,
    cdr_token_uid,
    session_id="",
    cdr_location=None,
):
    if cdr_location is None:
        cdr_location = CdrLocation.objects.create(
            uid=f"TEST-LOC-{uid}",
            address="Test St 1",
            city="Test City",
            country="FIN",
            postal_code="0001",
            state="",
            latitude="60.0",
            longitude="24.0",
            evse_uid=f"EVSE-{uid}",
            evse_id=f"FI*CPO*E-{uid}",
            connector_id="1",
            connector_standard="IEC_62196_T2",
            connector_format="SOCKET",
            connector_power_type="AC_3_PHASE",
        )

    return Cdr.objects.create(
        ocpi_master=ocpi_master,
        uid=uid,
        start_date_time=datetime(2024, 1, 15, 8, 0, 0, tzinfo=pytz.UTC),
        end_date_time=datetime(2024, 1, 15, 9, 30, 0, tzinfo=pytz.UTC),
        session_id=session_id,
        cdr_token=cdr_token,
        cdr_token_uid=cdr_token_uid,
        cdr_token_type="RFID",
        cdr_token_contract_id="CONTRACT-123",
        auth_method="RFID",
        cdr_location=cdr_location,
        currency="EUR",
        total_cost_excl_vat=10.0,
        total_cost_incl_vat=12.0,
        total_energy=50.0,
    )


@pytest.fixture(autouse=True)
def rollback_to_0043():
    """Ensure we're at migration 0043 before each test, so 0044 can be applied."""
    call_command("migrate", "ocpi22", "0043", verbosity=0)
    yield
    call_command("migrate", "ocpi22", "0043", verbosity=0)


class TestMigrationBackfillCdrCdrToken:
    """Test migration 0044: backfill Cdr.cdr_token FK from existing data."""

    @pytest.fixture(autouse=True)
    def setUp(self, cpo_credentialsrole, emsp_credentialsrole):
        self.cpo = cpo_credentialsrole
        self.emsp = emsp_credentialsrole

    def test_migration_backfills_cdr_when_matching_cdr_token_exists(
        self,
    ):
        _cdr_token = CdrTokenFactory(
            uid="RFID-LEGACY-123",
            token_type="RFID",
            contract_id="CONTRACT-123",
            ocpi_master=self.cpo,
        )

        legacy_cdr = _create_cdr(
            uid="LEGACY-CDR-001",
            ocpi_master=self.cpo,
            cdr_token=None,
            cdr_token_uid="RFID-LEGACY-123",
        )

        assert legacy_cdr.cdr_token is None

        call_command("migrate", "ocpi22", "0044_backfill_cdr_cdr_token", verbosity=0)

        legacy_cdr.refresh_from_db()
        assert legacy_cdr.cdr_token is not None
        assert legacy_cdr.cdr_token.uid == "RFID-LEGACY-123"

    def test_migration_backfills_cdr_via_session_when_no_cdr_token_match(
        self,
    ):
        session_with_cdr_token = OCPISessionFactory(
            uid="LEGACY-SESSION-001",
            cdr_token=CdrTokenFactory(
                uid="SESSION-TOKEN-456",
                ocpi_master=self.cpo,
            ),
            start_date_time=datetime(2024, 1, 15, 8, 0, 0, tzinfo=pytz.UTC),
            end_date_time=datetime(2024, 1, 15, 9, 30, 0, tzinfo=pytz.UTC),
            ocpi_master=self.cpo,
        )

        session_cdr = Session.objects.get(uid=session_with_cdr_token.uid)
        session_token = session_cdr.cdr_token

        _create_cdr(
            uid="LEGACY-CDR-VIA-SESSION",
            ocpi_master=self.cpo,
            cdr_token=None,
            cdr_token_uid="UNKNOWN-SESSION-TOKEN",
            session_id=session_with_cdr_token.uid,
        )

        call_command("migrate", "ocpi22", "0044_backfill_cdr_cdr_token", verbosity=0)

        migrated = Cdr.objects.get(uid="LEGACY-CDR-VIA-SESSION")
        assert migrated.cdr_token is not None
        assert migrated.cdr_token == session_token

    def test_migration_skips_cdr_that_already_has_fk_set(
        self,
    ):
        existing_token = CdrTokenFactory(
            uid="EXISTING-TOKEN",
            ocpi_master=self.cpo,
        )

        _create_cdr(
            uid="CDR-HAS-FK",
            ocpi_master=self.cpo,
            cdr_token=existing_token,
            cdr_token_uid="EXISTING-TOKEN",
        )

        existing_count = Cdr.objects.filter(cdr_token=existing_token).count()

        call_command("migrate", "ocpi22", "0044_backfill_cdr_cdr_token", verbosity=0)

        assert Cdr.objects.filter(cdr_token=existing_token).count() == existing_count

    def test_migration_leaves_null_when_no_match_found(
        self,
    ):
        _create_cdr(
            uid="LEGACY-CDR-NO-MATCH",
            ocpi_master=self.cpo,
            cdr_token=None,
            cdr_token_uid="DOES-NOT-EXIST",
        )

        call_command("migrate", "ocpi22", "0044_backfill_cdr_cdr_token", verbosity=0)

        migrated = Cdr.objects.get(uid="LEGACY-CDR-NO-MATCH")
        assert migrated.cdr_token is None

    def test_migration_backward_is_safe(
        self,
    ):
        _cdr_token = CdrTokenFactory(
            uid="BACKWARD-TOKEN",
            ocpi_master=self.cpo,
        )

        _create_cdr(
            uid="BACKWARD-CDR",
            ocpi_master=self.cpo,
            cdr_token=None,
            cdr_token_uid="BACKWARD-TOKEN",
        )

        call_command("migrate", "ocpi22", "0044_backfill_cdr_cdr_token", verbosity=0)

        forward_cdr = Cdr.objects.get(uid="BACKWARD-CDR")
        assert forward_cdr.cdr_token.uid == "BACKWARD-TOKEN"

        call_command("migrate", "ocpi22", "0043", verbosity=0)

        backward_cdr = Cdr.objects.get(uid="BACKWARD-CDR")
        assert backward_cdr.cdr_token is None
