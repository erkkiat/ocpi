import pytest
from datetime import datetime, timezone as dt_timezone
from django.utils import timezone

from ocpi22.choices import OcpiRolesEnum
from ocpi22.payments.exceptions import (
    TerminalAlreadyExistsError,
    FinancialAdviceConfirmationAlreadyExistsError,
    FinancialAdviceConfirmationValidationError,
    TerminalValidationError,
)
from ocpi22.payments.models import Terminal, FinancialAdviceConfirmation
from ocpi22.payments.services import TerminalService, FinancialAdviceConfirmationService
from ocpi22.payments.schemas import TerminalIn
from ocpi22.cpo.schemas import GeoLocation
from unittest.mock import patch
from ocpi22.tests.factories import (
    CredentialsRoleFactory,
    TerminalFactory,
    FinancialAdviceConfirmationFactory,
    LocationFactory,
    EvseFactory,
)


@pytest.fixture
def credentialsrole(db):
    return CredentialsRoleFactory(
        role=OcpiRolesEnum.PTP, party_id="PAY", country_code="NL"
    )


@pytest.fixture
def terminal_service():
    return TerminalService()


@pytest.fixture
def fac_service():
    return FinancialAdviceConfirmationService()


@pytest.fixture
def minimal_terminal_data():
    return {
        "terminal_id": "term-001",
        "customer_reference": "TEST-CUSTOMER-REF",
        "last_updated": datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt_timezone.utc),
    }


@pytest.fixture
def full_terminal_data():
    return {
        "terminal_id": "term-full-001",
        "customer_reference": "TEST-CUSTOMER-REF",
        "address": "Street 1",
        "city": "Helsinki",
        "postal_code": "00100",
        "country": "FIN",
        "latitude": "60.169857",
        "longitude": "24.938379",
        "invoice_base_url": "https://invoices.example.com",
        "invoice_creator": "CPO",
        "last_updated": timezone.now(),
    }


@pytest.fixture
def fac_data():
    return {
        "fac_id": "fac-001",
        "authorization_reference": "auth-ref-001",
        "total_cost_excl_vat": 10.50,
        "total_cost_incl_vat": 12.60,
        "currency": "EUR",
        "eft_data": ["Mastercard", "AID: 1234"],
        "capture_status_code": "SUCCESS",
        "last_updated": timezone.now(),
    }


@pytest.mark.django_db
class TestTerminalServiceCreate:
    def test_create_terminal_persists_terminal_to_database(
        self, terminal_service, credentialsrole, minimal_terminal_data
    ):
        terminal_service.create_terminal(minimal_terminal_data, credentialsrole)

        assert Terminal.objects.filter(terminal_id="term-001").exists()

    def test_create_terminal_returns_terminal_instance_with_correct_id(
        self, terminal_service, credentialsrole, minimal_terminal_data
    ):
        terminal = terminal_service.create_terminal(
            minimal_terminal_data, credentialsrole
        )

        assert terminal.terminal_id == "term-001"

    def test_create_terminal_assigns_credentials_from_credentialsrole(
        self, terminal_service, credentialsrole, minimal_terminal_data
    ):
        terminal = terminal_service.create_terminal(
            minimal_terminal_data, credentialsrole
        )

        assert terminal.credentials == credentialsrole.credentials

    def test_create_terminal_persists_all_optional_fields(
        self, terminal_service, credentialsrole, full_terminal_data
    ):
        terminal = terminal_service.create_terminal(full_terminal_data, credentialsrole)

        assert terminal.customer_reference == "TEST-CUSTOMER-REF"
        assert terminal.address == "Street 1"
        assert terminal.city == "Helsinki"
        assert terminal.postal_code == "00100"
        assert terminal.country == "FIN"
        assert terminal.latitude == "60.169857"
        assert terminal.longitude == "24.938379"
        assert terminal.invoice_base_url == "https://invoices.example.com"
        assert terminal.invoice_creator == "CPO"

    def test_create_terminal_raises_when_customer_reference_country_code_and_party_id_are_all_missing(
        self, terminal_service, credentialsrole
    ):
        from django.core.exceptions import ValidationError

        with pytest.raises(
            ValidationError, match="must have either a customer_reference"
        ):
            terminal_service.create_terminal(
                {"terminal_id": "term-bare"}, credentialsrole
            )

    def test_create_terminal_raises_when_terminal_id_already_exists_for_same_credentials(
        self, terminal_service, credentialsrole, minimal_terminal_data
    ):
        terminal_service.create_terminal(minimal_terminal_data, credentialsrole)

        with pytest.raises(TerminalAlreadyExistsError):
            terminal_service.create_terminal(
                minimal_terminal_data.copy(), credentialsrole
            )

    def test_create_terminal_does_not_persist_second_terminal_when_duplicate_raises(
        self, terminal_service, credentialsrole, minimal_terminal_data
    ):
        terminal_service.create_terminal(minimal_terminal_data, credentialsrole)

        with pytest.raises(TerminalAlreadyExistsError):
            terminal_service.create_terminal(
                minimal_terminal_data.copy(), credentialsrole
            )

        assert Terminal.objects.filter(terminal_id="term-001").count() == 1

    def test_create_terminal_raises_when_terminal_id_already_exists_for_different_credentials(
        self, terminal_service, credentialsrole, minimal_terminal_data
    ):
        other_credentialsrole = CredentialsRoleFactory(
            role=OcpiRolesEnum.PTP, party_id="OTH", country_code="FI"
        )
        terminal_service.create_terminal(minimal_terminal_data, credentialsrole)

        with pytest.raises(TerminalAlreadyExistsError):
            terminal_service.create_terminal(
                minimal_terminal_data.copy(), other_credentialsrole
            )


@pytest.mark.django_db
class TestTerminalServiceGet:
    def test_get_terminal_by_id_returns_terminal_when_found(
        self, terminal_service, credentialsrole
    ):
        TerminalFactory(
            terminal_id="term-get-001", credentials=credentialsrole.credentials
        )

        result = terminal_service.get_terminal_by_id("term-get-001", credentialsrole)

        assert result is not None
        assert result.terminal_id == "term-get-001"

    def test_get_terminal_by_id_returns_none_when_not_found(
        self, terminal_service, credentialsrole
    ):
        result = terminal_service.get_terminal_by_id("nonexistent", credentialsrole)

        assert result is None

    def test_get_terminal_by_id_returns_none_when_terminal_belongs_to_different_credentials(
        self, terminal_service, credentialsrole
    ):
        other_credentialsrole = CredentialsRoleFactory(
            role=OcpiRolesEnum.PTP, party_id="OTH", country_code="FI"
        )
        TerminalFactory(
            terminal_id="term-other", credentials=other_credentialsrole.credentials
        )

        result = terminal_service.get_terminal_by_id("term-other", credentialsrole)

        assert result is None

    def test_get_terminals_returns_all_terminals_for_credentials(
        self, terminal_service, credentialsrole
    ):
        TerminalFactory.create_batch(3, credentials=credentialsrole.credentials)

        result = terminal_service.get_terminals(credentialsrole)

        assert result.count() == 3

    def test_get_terminals_returns_empty_queryset_when_no_terminals(
        self, terminal_service, credentialsrole
    ):
        result = terminal_service.get_terminals(credentialsrole)

        assert result.count() == 0

    def test_get_terminals_does_not_return_terminals_of_other_credentials(
        self, terminal_service, credentialsrole
    ):
        other_credentialsrole = CredentialsRoleFactory(
            role=OcpiRolesEnum.PTP, party_id="OTH", country_code="FI"
        )
        TerminalFactory(
            terminal_id="term-foreign", credentials=other_credentialsrole.credentials
        )
        TerminalFactory(
            terminal_id="term-ours", credentials=credentialsrole.credentials
        )

        result = terminal_service.get_terminals(credentialsrole)

        assert list(result.values_list("terminal_id", flat=True)) == ["term-ours"]

    def test_get_terminals_returns_queryset_ordered_by_created(
        self, terminal_service, credentialsrole
    ):
        TerminalFactory(terminal_id="term-z", credentials=credentialsrole.credentials)
        TerminalFactory(terminal_id="term-a", credentials=credentialsrole.credentials)
        TerminalFactory(terminal_id="term-m", credentials=credentialsrole.credentials)

        result = list(terminal_service.get_terminals(credentialsrole))

        assert [t.terminal_id for t in result] == ["term-z", "term-a", "term-m"]


@pytest.mark.django_db
class TestFACServiceCreate:
    def test_create_fac_persists_fac_to_database(
        self, fac_service, credentialsrole, fac_data
    ):
        fac_service.create_fac(fac_data, credentialsrole)

        assert FinancialAdviceConfirmation.objects.filter(fac_id="fac-001").exists()

    def test_create_fac_returns_fac_instance_with_correct_id(
        self, fac_service, credentialsrole, fac_data
    ):
        fac = fac_service.create_fac(fac_data, credentialsrole)

        assert fac.fac_id == "fac-001"

    def test_create_fac_assigns_credentials_from_credentialsrole(
        self, fac_service, credentialsrole, fac_data
    ):
        fac = fac_service.create_fac(fac_data, credentialsrole)

        assert fac.credentials == credentialsrole.credentials

    def test_create_fac_persists_all_fields(
        self, fac_service, credentialsrole, fac_data
    ):
        fac = fac_service.create_fac(fac_data, credentialsrole)

        assert fac.authorization_reference == "auth-ref-001"
        assert fac.total_cost_excl_vat == 10.50
        assert fac.total_cost_incl_vat == 12.60
        assert fac.currency == "EUR"
        assert fac.eft_data == ["Mastercard", "AID: 1234"]
        assert fac.capture_status_code == "SUCCESS"

    def test_create_fac_links_terminal_when_terminal_id_provided(
        self, fac_service, credentialsrole, fac_data
    ):
        terminal = TerminalFactory(
            terminal_id="term-for-fac", credentials=credentialsrole.credentials
        )

        fac = fac_service.create_fac(
            fac_data, credentialsrole, terminal_id=terminal.terminal_id
        )

        assert fac.terminal is not None
        assert fac.terminal.terminal_id == "term-for-fac"

    def test_create_fac_sets_terminal_to_none_when_no_terminal_id_provided(
        self, fac_service, credentialsrole, fac_data
    ):
        fac = fac_service.create_fac(fac_data, credentialsrole)

        assert fac.terminal is None

    def test_create_fac_raises_when_fac_id_already_exists_for_same_credentials(
        self, fac_service, credentialsrole, fac_data
    ):
        fac_service.create_fac(fac_data, credentialsrole)

        with pytest.raises(FinancialAdviceConfirmationAlreadyExistsError):
            fac_service.create_fac(fac_data.copy(), credentialsrole)

    def test_create_fac_does_not_persist_second_fac_when_duplicate_raises(
        self, fac_service, credentialsrole, fac_data
    ):
        fac_service.create_fac(fac_data, credentialsrole)

        with pytest.raises(FinancialAdviceConfirmationAlreadyExistsError):
            fac_service.create_fac(fac_data.copy(), credentialsrole)

        assert FinancialAdviceConfirmation.objects.filter(fac_id="fac-001").count() == 1

    def test_create_fac_raises_when_terminal_id_does_not_exist_for_credentials(
        self, fac_service, credentialsrole, fac_data
    ):
        with pytest.raises(FinancialAdviceConfirmationValidationError):
            fac_service.create_fac(
                fac_data, credentialsrole, terminal_id="nonexistent-terminal"
            )

    def test_create_fac_does_not_persist_fac_when_terminal_not_found(
        self, fac_service, credentialsrole, fac_data
    ):
        with pytest.raises(FinancialAdviceConfirmationValidationError):
            fac_service.create_fac(
                fac_data, credentialsrole, terminal_id="nonexistent-terminal"
            )

        assert not FinancialAdviceConfirmation.objects.filter(fac_id="fac-001").exists()

    def test_create_fac_raises_when_terminal_belongs_to_different_credentials(
        self, fac_service, credentialsrole, fac_data
    ):
        other_credentialsrole = CredentialsRoleFactory(
            role=OcpiRolesEnum.PTP, party_id="OTH", country_code="FI"
        )
        terminal = TerminalFactory(
            terminal_id="term-other-party",
            credentials=other_credentialsrole.credentials,
        )

        with pytest.raises(FinancialAdviceConfirmationValidationError):
            fac_service.create_fac(
                fac_data, credentialsrole, terminal_id=terminal.terminal_id
            )


@pytest.mark.django_db
class TestFACServiceGet:
    def test_get_fac_by_id_returns_fac_when_found(self, fac_service, credentialsrole):
        FinancialAdviceConfirmationFactory(
            fac_id="fac-get-001", credentials=credentialsrole.credentials
        )

        result = fac_service.get_fac_by_id("fac-get-001", credentialsrole)

        assert result is not None
        assert result.fac_id == "fac-get-001"

    def test_get_fac_by_id_returns_none_when_not_found(
        self, fac_service, credentialsrole
    ):
        result = fac_service.get_fac_by_id("nonexistent", credentialsrole)

        assert result is None

    def test_get_fac_by_id_returns_none_when_fac_belongs_to_different_credentials(
        self, fac_service, credentialsrole
    ):
        other_credentialsrole = CredentialsRoleFactory(
            role=OcpiRolesEnum.PTP, party_id="OTH", country_code="FI"
        )
        FinancialAdviceConfirmationFactory(
            fac_id="fac-other", credentials=other_credentialsrole.credentials
        )

        result = fac_service.get_fac_by_id("fac-other", credentialsrole)

        assert result is None

    def test_get_facs_returns_all_facs_for_credentials(
        self, fac_service, credentialsrole
    ):
        FinancialAdviceConfirmationFactory.create_batch(
            2, credentials=credentialsrole.credentials
        )

        result = fac_service.get_facs(credentialsrole)

        assert result.count() == 2

    def test_get_facs_returns_empty_queryset_when_no_facs(
        self, fac_service, credentialsrole
    ):
        result = fac_service.get_facs(credentialsrole)

        assert result.count() == 0

    def test_get_facs_does_not_return_facs_of_other_credentials(
        self, fac_service, credentialsrole
    ):
        other_credentialsrole = CredentialsRoleFactory(
            role=OcpiRolesEnum.PTP, party_id="OTH", country_code="FI"
        )
        FinancialAdviceConfirmationFactory(
            fac_id="fac-foreign", credentials=other_credentialsrole.credentials
        )
        FinancialAdviceConfirmationFactory(
            fac_id="fac-ours", credentials=credentialsrole.credentials
        )

        result = fac_service.get_facs(credentialsrole)

        assert list(result.values_list("fac_id", flat=True)) == ["fac-ours"]


@pytest.mark.django_db
class TestTerminalServiceUpdate:
    def test_put_terminal_replaces_invoice_base_url_locations_and_evses(
        self, terminal_service, credentialsrole
    ):
        location = LocationFactory(uid="LOC-PUT")
        evse = EvseFactory(uid="EVSE-PUT", location=location)

        terminal = TerminalFactory(
            terminal_id="terminal-put",
            credentials=credentialsrole.credentials,
            invoice_base_url="https://example-url-for-invoices-old.com",
        )

        payload = TerminalIn(
            terminal_id="terminal-put",
            customer_reference="TEST-CUSTOMER-REF",
            invoice_base_url="https://example-url-for-invoices-new.com",
            location_ids=[location.uid],
            evse_uids=[evse.uid],
        )

        updated_terminal = terminal_service.put_terminal(terminal, payload)

        assert (
            updated_terminal.invoice_base_url
            == "https://example-url-for-invoices-new.com"
        )
        assert list(updated_terminal.locations.all()) == [location]
        assert list(updated_terminal.evses.all()) == [evse]

    def test_patch_terminal_updates_invoice_base_url_locations_and_auto_populates_evses_when_only_location_ids_provided(
        self, terminal_service, credentialsrole
    ):
        location = LocationFactory(uid="LOC-PATCH")
        evse = EvseFactory(uid="EVSE-PATCH", location=location)
        terminal = TerminalFactory(
            terminal_id="terminal-patch",
            credentials=credentialsrole.credentials,
            invoice_base_url="https://example-url-for-invoices-old.com",
        )

        payload = TerminalIn(
            terminal_id="terminal-patch",
            customer_reference="TEST-CUSTOMER-REF",
            invoice_base_url="https://example-url-for-invoices-new.com",
            location_ids=[location.uid],
        )

        updated_terminal = terminal_service.patch_terminal(terminal, payload)

        assert (
            updated_terminal.invoice_base_url
            == "https://example-url-for-invoices-new.com"
        )
        assert list(updated_terminal.locations.all()) == [location]
        assert list(updated_terminal.evses.all()) == [evse]

    def test_put_terminal_raises_terminal_validation_error_when_location_uid_does_not_exist_in_database(
        self, terminal_service, credentialsrole
    ):
        terminal = TerminalFactory(
            terminal_id="term-fail-put", credentials=credentialsrole.credentials
        )

        payload = TerminalIn(
            terminal_id="term-fail-put",
            customer_reference=terminal.customer_reference,
            location_ids=["NON-EXISTENT-LOC"],
        )

        with pytest.raises(TerminalValidationError) as exc_info:
            terminal_service.put_terminal(terminal, payload)

        assert "NON-EXISTENT-LOC" in str(exc_info.value)

    def test_patch_terminal_raises_terminal_validation_error_when_evse_uid_does_not_exist_in_database(
        self, terminal_service, credentialsrole
    ):
        terminal = TerminalFactory(
            terminal_id="term-fail-patch", credentials=credentialsrole.credentials
        )

        payload = TerminalIn(
            terminal_id="term-fail-patch", evse_uids=["NON-EXISTENT-EVSE"]
        )

        with pytest.raises(TerminalValidationError) as exc_info:
            terminal_service.patch_terminal(terminal, payload)

        assert "NON-EXISTENT-EVSE" in str(exc_info.value)

    def test_validate_locations_raises_terminal_validation_error_when_location_uid_does_not_exist_in_database(
        self, terminal_service
    ):
        location = LocationFactory(uid="LOC-EXIST")

        with pytest.raises(TerminalValidationError) as exc_info:
            terminal_service._validate_locations([location.uid, "MISSING-LOC"])

        assert "MISSING-LOC" in str(exc_info.value)

    def test_validate_evses_raises_terminal_validation_error_when_evse_uid_does_not_exist_in_database(
        self, terminal_service
    ):
        location = LocationFactory(uid="LOC-E")
        evse = EvseFactory(uid="EVSE-EXIST", location=location)

        with pytest.raises(TerminalValidationError) as exc_info:
            terminal_service._validate_evses([evse.uid, "MISSING-EVSE"])

        assert "MISSING-EVSE" in str(exc_info.value)

    def test_put_terminal_sets_location_fields_address_city_postal_code_state_country(
        self, terminal_service, credentialsrole
    ):
        terminal = TerminalFactory(
            terminal_id="term-put-addr",
            credentials=credentialsrole.credentials,
            address="Old Street 1",
            city="OldCity",
        )
        location = LocationFactory(uid="LOC-ADDR")
        EvseFactory(uid="EVSE-ADDR", location=location)

        payload = TerminalIn(
            terminal_id="term-put-addr",
            customer_reference="TEST-CUSTOMER-REF",
            address="New Street 99",
            city="Helsinki",
            postal_code="00100",
            state="Uusimaa",
            country="FIN",
            location_ids=[location.uid],
        )

        updated = terminal_service.put_terminal(terminal, payload)

        assert updated.address == "New Street 99"
        assert updated.city == "Helsinki"
        assert updated.postal_code == "00100"
        assert updated.state == "Uusimaa"
        assert updated.country == "FIN"

    def test_put_terminal_sets_coordinates_from_coordinates_field(
        self, terminal_service, credentialsrole
    ):
        terminal = TerminalFactory(
            terminal_id="term-put-coord", credentials=credentialsrole.credentials
        )
        location = LocationFactory(uid="LOC-COORD")
        EvseFactory(uid="EVSE-COORD", location=location)

        payload = TerminalIn(
            terminal_id="term-put-coord",
            customer_reference="TEST-CUSTOMER-REF",
            coordinates=GeoLocation(latitude="60.169857", longitude="24.938379"),
            location_ids=[location.uid],
        )

        updated = terminal_service.put_terminal(terminal, payload)

        assert updated.latitude == "60.169857"
        assert updated.longitude == "24.938379"

    def test_put_terminal_clears_coordinates_when_not_provided(
        self, terminal_service, credentialsrole
    ):
        terminal = TerminalFactory(
            terminal_id="term-put-clear-coord",
            credentials=credentialsrole.credentials,
            latitude="60.169857",
            longitude="24.938379",
        )
        location = LocationFactory(uid="LOC-CLEAR-COORD")
        EvseFactory(uid="EVSE-CLEAR-COORD", location=location)

        payload = TerminalIn(
            terminal_id="term-put-clear-coord",
            customer_reference="TEST-CUSTOMER-REF",
            location_ids=[location.uid],
        )

        updated = terminal_service.put_terminal(terminal, payload)

        assert updated.latitude is None
        assert updated.longitude is None

    def test_put_terminal_clears_location_fields_when_not_provided(
        self, terminal_service, credentialsrole
    ):
        terminal = TerminalFactory(
            terminal_id="term-put-clear-addr",
            credentials=credentialsrole.credentials,
            address="Old Street 1",
            city="OldCity",
        )
        location = LocationFactory(uid="LOC-CLEAR-ADDR")
        EvseFactory(uid="EVSE-CLEAR-ADDR", location=location)

        payload = TerminalIn(
            terminal_id="term-put-clear-addr",
            customer_reference="TEST-CUSTOMER-REF",
            location_ids=[location.uid],
        )

        updated = terminal_service.put_terminal(terminal, payload)

        assert updated.address is None
        assert updated.city is None

    def test_patch_terminal_updates_only_address_when_provided(
        self, terminal_service, credentialsrole
    ):
        terminal = TerminalFactory(
            terminal_id="term-patch-addr",
            credentials=credentialsrole.credentials,
            address="Old Street 1",
            city="Helsinki",
        )
        location = LocationFactory(uid="LOC-PATCH-ADDR")
        EvseFactory(uid="EVSE-PATCH-ADDR", location=location)

        payload = TerminalIn(
            terminal_id="term-patch-addr",
            address="New Street 99",
            location_ids=[location.uid],
        )

        updated = terminal_service.patch_terminal(terminal, payload)

        assert updated.address == "New Street 99"
        assert updated.city == "Helsinki"

    def test_patch_terminal_updates_coordinates_when_provided(
        self, terminal_service, credentialsrole
    ):
        terminal = TerminalFactory(
            terminal_id="term-patch-coord", credentials=credentialsrole.credentials
        )
        location = LocationFactory(uid="LOC-PATCH-COORD")
        EvseFactory(uid="EVSE-PATCH-COORD", location=location)

        payload = TerminalIn(
            terminal_id="term-patch-coord",
            coordinates=GeoLocation(latitude="52.372294", longitude="4.898632"),
            location_ids=[location.uid],
        )

        updated = terminal_service.patch_terminal(terminal, payload)

        assert updated.latitude == "52.372294"
        assert updated.longitude == "4.898632"

    def test_patch_terminal_clears_coordinates_when_null_provided(
        self, terminal_service, credentialsrole
    ):
        terminal = TerminalFactory(
            terminal_id="term-patch-null-coord",
            credentials=credentialsrole.credentials,
            latitude="60.169857",
            longitude="24.938379",
        )
        location = LocationFactory(uid="LOC-PATCH-NULL-COORD")
        EvseFactory(uid="EVSE-PATCH-NULL-COORD", location=location)

        payload = TerminalIn(
            terminal_id="term-patch-null-coord",
            coordinates=None,
            location_ids=[location.uid],
        )

        updated = terminal_service.patch_terminal(terminal, payload)

        assert updated.latitude is None
        assert updated.longitude is None

    def test_patch_terminal_does_not_clear_location_fields_when_not_in_payload(
        self, terminal_service, credentialsrole
    ):
        terminal = TerminalFactory(
            terminal_id="term-patch-keep-addr",
            credentials=credentialsrole.credentials,
            address="Preserved Street 1",
            city="PreservedCity",
        )
        location = LocationFactory(uid="LOC-PATCH-KEEP")
        EvseFactory(uid="EVSE-PATCH-KEEP", location=location)

        payload = TerminalIn(
            terminal_id="term-patch-keep-addr",
            location_ids=[location.uid],
        )

        updated = terminal_service.patch_terminal(terminal, payload)

        assert updated.address == "Preserved Street 1"
        assert updated.city == "PreservedCity"

    @patch("ocpi22.payments.services.send_ocpi_request")
    @patch("ocpi22.payments.services.get_our_party")
    @patch("ocpi22.payments.services.find_endpoints_by_roles")
    def test_send_to_ptp_calls_send_ocpi_request_with_correct_url_method_and_data(
        self,
        mock_find_endpoints,
        mock_get_party,
        mock_send,
        terminal_service,
        credentialsrole,
    ):
        mock_find_endpoints.return_value = [
            (
                "https://ptp.com/ocpi/payments",
                None,
                None,
                None,
                credentialsrole.credentials,
            )
        ]
        mock_party = type("OurParty", (), {"country_code": "FI", "party_id": "CPO"})
        mock_get_party.return_value = mock_party

        terminal = TerminalFactory(
            terminal_id="terminal001", credentials=credentialsrole.credentials
        )

        terminal_service._send_to_ptp(
            terminal, "patch", {"terminal_id": "terminal001", "location_ids": []}
        )

        mock_send.apply_async.assert_called_once()
        kwargs = mock_send.apply_async.call_args[1]["kwargs"]
        assert kwargs["url"] == "https://ptp.com/ocpi/payments/terminals/terminal001"
        assert kwargs["method"] == "patch"
        assert kwargs["data"]["terminal_id"] == "terminal001"
        assert kwargs["data"]["location_ids"] == []
        assert kwargs["data"]["evse_uids"] == []

    @patch("ocpi22.payments.services.send_ocpi_request")
    def test_send_to_ptp_does_not_send_request_when_no_credentials_found(
        self, mock_send, terminal_service
    ):
        terminal = TerminalFactory(
            terminal_id="terminal-no-credentials", credentials=None
        )

        terminal_service._send_to_ptp(terminal, "put", {})

        mock_send.apply_async.assert_not_called()

    @patch("ocpi22.payments.services.send_ocpi_request")
    def test_send_to_ptp_does_not_send_request_when_no_role_found(
        self, mock_send, terminal_service, credentialsrole
    ):
        credentialsrole.delete()
        terminal = TerminalFactory(
            terminal_id="terminal-no-role", credentials=credentialsrole.credentials
        )

        terminal_service._send_to_ptp(terminal, "put", {})

        mock_send.apply_async.assert_not_called()

    @patch("ocpi22.payments.services.send_ocpi_request")
    @patch("ocpi22.payments.services.find_endpoints_by_roles")
    def test_send_to_ptp_does_not_send_request_when_no_endpoint_found(
        self, mock_find_endpoints, mock_send, terminal_service, credentialsrole
    ):
        mock_find_endpoints.return_value = []
        terminal = TerminalFactory(
            terminal_id="terminal-no-endpoints", credentials=credentialsrole.credentials
        )

        terminal_service._send_to_ptp(terminal, "put", {})

        mock_send.apply_async.assert_not_called()


@pytest.mark.django_db
class TestTerminalInSchema:
    def test_terminal_in_last_updated_defaults_to_utc_now_when_not_provided(self):
        before = datetime.now(dt_timezone.utc)
        payload = TerminalIn(terminal_id="term-ts", location_ids=["LOC-1"])
        after = datetime.now(dt_timezone.utc)

        assert payload.last_updated is not None
        assert before <= payload.last_updated <= after
        assert payload.last_updated.tzinfo is not None

    def test_terminal_in_last_updated_uses_provided_value_when_given(self):
        fixed_dt = datetime(2024, 6, 15, 10, 0, 0, tzinfo=dt_timezone.utc)
        payload = TerminalIn(
            terminal_id="term-ts-explicit",
            location_ids=["LOC-1"],
            last_updated=fixed_dt,
        )

        assert payload.last_updated == fixed_dt

    def test_terminal_in_raises_when_neither_location_ids_nor_evse_uids_provided(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            TerminalIn(terminal_id="term-no-loc")

    def test_terminal_in_accepts_only_location_ids_without_evse_uids(self):
        payload = TerminalIn(terminal_id="term-loc-only", location_ids=["LOC-A"])

        assert payload.location_ids == ["LOC-A"]
        assert payload.evse_uids == []

    def test_terminal_in_accepts_only_evse_uids_without_location_ids(self):
        payload = TerminalIn(terminal_id="term-evse-only", evse_uids=["EVSE-A"])

        assert payload.evse_uids == ["EVSE-A"]
        assert payload.location_ids == []

    def test_terminal_in_accepts_both_location_ids_and_evse_uids(self):
        payload = TerminalIn(
            terminal_id="term-both",
            location_ids=["LOC-A"],
            evse_uids=["EVSE-A"],
        )

        assert payload.location_ids == ["LOC-A"]
        assert payload.evse_uids == ["EVSE-A"]


@pytest.mark.django_db
class TestSendToPtpEnrichment:
    @patch("ocpi22.payments.services.send_ocpi_request")
    @patch("ocpi22.payments.services.get_our_party")
    @patch("ocpi22.payments.services.find_endpoints_by_roles")
    def test_send_to_ptp_sends_location_and_evse_uids_from_terminal_not_from_payload(
        self, mock_find_endpoints, mock_get_party, mock_send, terminal_service, credentialsrole
    ):
        location = LocationFactory(uid="LOC-TERMINAL-STATE")
        evse = EvseFactory(uid="EVSE-TERMINAL-STATE", location=location)

        mock_find_endpoints.return_value = [
            ("https://ptp.com/ocpi/payments", None, None, None, credentialsrole.credentials)
        ]
        mock_party = type("OurParty", (), {"country_code": "FI", "party_id": "CPO"})
        mock_get_party.return_value = mock_party

        terminal = TerminalFactory(terminal_id="term-state-check", credentials=credentialsrole.credentials)
        terminal.locations.set([location])
        terminal.evses.set([evse])

        terminal_service._send_to_ptp(
            terminal, "put", {"terminal_id": "term-state-check", "location_ids": ["STALE"], "evse_uids": ["STALE"]}
        )

        mock_send.apply_async.assert_called_once()
        sent_data = mock_send.apply_async.call_args[1]["kwargs"]["data"]
        assert sent_data["location_ids"] == [location.uid]
        assert sent_data["evse_uids"] == [evse.uid]

    @patch("ocpi22.payments.services.send_ocpi_request")
    @patch("ocpi22.payments.services.get_our_party")
    @patch("ocpi22.payments.services.find_endpoints_by_roles")
    def test_send_to_ptp_payload_uses_location_ids_key_not_location_uids(
        self, mock_find_endpoints, mock_get_party, mock_send, terminal_service, credentialsrole
    ):
        mock_find_endpoints.return_value = [
            ("https://ptp.com/ocpi/payments", None, None, None, credentialsrole.credentials)
        ]
        mock_party = type("OurParty", (), {"country_code": "FI", "party_id": "CPO"})
        mock_get_party.return_value = mock_party

        terminal = TerminalFactory(terminal_id="term-key-check", credentials=credentialsrole.credentials)

        terminal_service._send_to_ptp(
            terminal,
            "put",
            {"terminal_id": "term-key-check", "location_ids": ["LOC-Y"], "evse_uids": ["EVSE-Y"]},
        )

        mock_send.apply_async.assert_called_once()
        sent_data = mock_send.apply_async.call_args[1]["kwargs"]["data"]
        assert "location_ids" in sent_data
        assert "location_uids" not in sent_data


@pytest.mark.django_db
class TestResolveLocationsAndEvses:
    def test_put_terminal_auto_populates_evses_when_only_location_ids_given(
        self, terminal_service, credentialsrole
    ):
        location = LocationFactory(uid="LOC-AUTO-EVSE")
        evse1 = EvseFactory(uid="EVSE-AUTO-1", location=location)
        evse2 = EvseFactory(uid="EVSE-AUTO-2", location=location)
        terminal = TerminalFactory(
            terminal_id="term-auto-evse", credentials=credentialsrole.credentials
        )

        payload = TerminalIn(
            terminal_id="term-auto-evse",
            customer_reference="TEST-CUSTOMER-REF",
            location_ids=[location.uid],
        )

        updated = terminal_service.put_terminal(terminal, payload)

        assert set(updated.evses.values_list("uid", flat=True)) == {evse1.uid, evse2.uid}
        assert list(updated.locations.values_list("uid", flat=True)) == [location.uid]

    def test_put_terminal_auto_populates_locations_when_only_evse_uids_given(
        self, terminal_service, credentialsrole
    ):
        location = LocationFactory(uid="LOC-AUTO-LOC")
        evse = EvseFactory(uid="EVSE-AUTO-LOC", location=location)
        terminal = TerminalFactory(
            terminal_id="term-auto-loc", credentials=credentialsrole.credentials
        )

        payload = TerminalIn(
            terminal_id="term-auto-loc",
            customer_reference="TEST-CUSTOMER-REF",
            evse_uids=[evse.uid],
        )

        updated = terminal_service.put_terminal(terminal, payload)

        assert list(updated.evses.values_list("uid", flat=True)) == [evse.uid]
        assert list(updated.locations.values_list("uid", flat=True)) == [location.uid]

    def test_put_terminal_raises_terminal_validation_error_when_location_has_no_evses_in_database(
        self, terminal_service, credentialsrole
    ):
        location = LocationFactory(uid="LOC-EMPTY")
        terminal = TerminalFactory(
            terminal_id="term-loc-empty", credentials=credentialsrole.credentials
        )

        payload = TerminalIn(
            terminal_id="term-loc-empty",
            customer_reference="TEST-CUSTOMER-REF",
            location_ids=[location.uid],
        )

        with pytest.raises(TerminalValidationError, match="LOC-EMPTY"):
            terminal_service.put_terminal(terminal, payload)

    def test_put_terminal_raises_when_evse_does_not_belong_to_given_location(
        self, terminal_service, credentialsrole
    ):
        location_a = LocationFactory(uid="LOC-A-CROSS")
        location_b = LocationFactory(uid="LOC-B-CROSS")
        evse_a = EvseFactory(uid="EVSE-A-CROSS", location=location_a)
        evse_b = EvseFactory(uid="EVSE-B-CROSS", location=location_b)
        terminal = TerminalFactory(
            terminal_id="term-cross", credentials=credentialsrole.credentials
        )

        payload = TerminalIn(
            terminal_id="term-cross",
            customer_reference="TEST-CUSTOMER-REF",
            location_ids=[location_a.uid],
            evse_uids=[evse_a.uid, evse_b.uid],
        )

        with pytest.raises(TerminalValidationError, match="EVSE-B-CROSS"):
            terminal_service.put_terminal(terminal, payload)

    def test_put_terminal_raises_terminal_validation_error_when_location_has_no_evse_in_given_evse_list(
        self, terminal_service, credentialsrole
    ):
        location_a = LocationFactory(uid="LOC-COVERED")
        location_b = LocationFactory(uid="LOC-UNCOVERED")
        evse_a = EvseFactory(uid="EVSE-COVERED", location=location_a)
        EvseFactory(uid="EVSE-UNCOVERED", location=location_b)
        terminal = TerminalFactory(
            terminal_id="term-uncovered-loc", credentials=credentialsrole.credentials
        )

        payload = TerminalIn(
            terminal_id="term-uncovered-loc",
            customer_reference="TEST-CUSTOMER-REF",
            location_ids=[location_a.uid, location_b.uid],
            evse_uids=[evse_a.uid],
        )

        with pytest.raises(TerminalValidationError, match="LOC-UNCOVERED"):
            terminal_service.put_terminal(terminal, payload)

    def test_put_terminal_allows_partial_evse_selection_within_locations(
        self, terminal_service, credentialsrole
    ):
        location = LocationFactory(uid="LOC-PARTIAL")
        evse1 = EvseFactory(uid="EVSE-1", location=location)
        EvseFactory(uid="EVSE-2", location=location)
        terminal = TerminalFactory(
            terminal_id="term-evse-1", credentials=credentialsrole.credentials
        )

        payload = TerminalIn(
            terminal_id="term-evse-1",
            customer_reference="TEST-CUSTOMER-REF",
            location_ids=[location.uid],
            evse_uids=[evse1.uid],
        )

        updated = terminal_service.put_terminal(terminal, payload)

        assert list(updated.evses.values_list("uid", flat=True)) == [evse1.uid]

    def test_patch_terminal_auto_populates_evses_when_only_location_ids_given(
        self, terminal_service, credentialsrole
    ):
        location = LocationFactory(uid="LOC-PATCH-AUTO")
        evse1 = EvseFactory(uid="EVSE-PATCH-AUTO-1", location=location)
        evse2 = EvseFactory(uid="EVSE-PATCH-AUTO-2", location=location)
        terminal = TerminalFactory(
            terminal_id="term-patch-auto-evse", credentials=credentialsrole.credentials
        )

        payload = TerminalIn(
            terminal_id="term-patch-auto-evse",
            location_ids=[location.uid],
        )

        updated = terminal_service.patch_terminal(terminal, payload)

        assert set(updated.evses.values_list("uid", flat=True)) == {evse1.uid, evse2.uid}
        assert list(updated.locations.values_list("uid", flat=True)) == [location.uid]

    def test_patch_terminal_auto_populates_locations_when_only_evse_uids_given(
        self, terminal_service, credentialsrole
    ):
        location = LocationFactory(uid="LOC-PATCH-AUTO-LOC")
        evse = EvseFactory(uid="EVSE-PATCH-AUTO-LOC", location=location)
        terminal = TerminalFactory(
            terminal_id="term-patch-auto-loc", credentials=credentialsrole.credentials
        )

        payload = TerminalIn(
            terminal_id="term-patch-auto-loc",
            evse_uids=[evse.uid],
        )

        updated = terminal_service.patch_terminal(terminal, payload)

        assert list(updated.evses.values_list("uid", flat=True)) == [evse.uid]
        assert list(updated.locations.values_list("uid", flat=True)) == [location.uid]

    def test_patch_terminal_raises_terminal_validation_error_when_location_has_no_evses_in_database(
        self, terminal_service, credentialsrole
    ):
        location = LocationFactory(uid="LOC-PATCH-EMPTY")
        terminal = TerminalFactory(
            terminal_id="term-patch-loc-empty", credentials=credentialsrole.credentials
        )

        payload = TerminalIn(
            terminal_id="term-patch-loc-empty",
            location_ids=[location.uid],
        )

        with pytest.raises(TerminalValidationError, match="LOC-PATCH-EMPTY"):
            terminal_service.patch_terminal(terminal, payload)

    def test_patch_terminal_raises_terminal_validation_error_when_evse_does_not_belong_to_given_location(
        self, terminal_service, credentialsrole
    ):
        location_a = LocationFactory(uid="LOC-A-PATCH-CROSS")
        location_b = LocationFactory(uid="LOC-B-PATCH-CROSS")
        evse_a = EvseFactory(uid="EVSE-A-PATCH-CROSS", location=location_a)
        evse_b = EvseFactory(uid="EVSE-B-PATCH-CROSS", location=location_b)
        terminal = TerminalFactory(
            terminal_id="term-patch-cross", credentials=credentialsrole.credentials
        )

        payload = TerminalIn(
            terminal_id="term-patch-cross",
            location_ids=[location_a.uid],
            evse_uids=[evse_a.uid, evse_b.uid],
        )

        with pytest.raises(TerminalValidationError, match="EVSE-B-PATCH-CROSS"):
            terminal_service.patch_terminal(terminal, payload)

    def test_patch_terminal_raises_terminal_validation_error_when_location_has_no_evse_in_given_evse_list(
        self, terminal_service, credentialsrole
    ):
        location_a = LocationFactory(uid="LOC-P-COVERED")
        location_b = LocationFactory(uid="LOC-P-UNCOVERED")
        evse_a = EvseFactory(uid="EVSE-P-COVERED", location=location_a)
        EvseFactory(uid="EVSE-P-UNCOVERED", location=location_b)
        terminal = TerminalFactory(
            terminal_id="term-patch-uncovered", credentials=credentialsrole.credentials
        )

        payload = TerminalIn(
            terminal_id="term-patch-uncovered",
            location_ids=[location_a.uid, location_b.uid],
            evse_uids=[evse_a.uid],
        )

        with pytest.raises(TerminalValidationError, match="LOC-P-UNCOVERED"):
            terminal_service.patch_terminal(terminal, payload)

    def test_patch_terminal_allows_partial_evse_selection_within_locations(
        self, terminal_service, credentialsrole
    ):
        location = LocationFactory(uid="LOC-PATCH-PARTIAL")
        evse1 = EvseFactory(uid="EVSE-PATCH-PARTIAL-1", location=location)
        EvseFactory(uid="EVSE-PATCH-PARTIAL-2", location=location)
        terminal = TerminalFactory(
            terminal_id="term-patch-partial", credentials=credentialsrole.credentials
        )

        payload = TerminalIn(
            terminal_id="term-patch-partial",
            location_ids=[location.uid],
            evse_uids=[evse1.uid],
        )

        updated = terminal_service.patch_terminal(terminal, payload)

        assert list(updated.evses.values_list("uid", flat=True)) == [evse1.uid]
