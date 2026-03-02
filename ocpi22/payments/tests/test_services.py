import pytest
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
    return {"terminal_id": "term-001"}


@pytest.fixture
def full_terminal_data():
    return {
        "terminal_id": "term-full-001",
        "customer_reference": "CUST-REF-001",
        "address": "Street 1",
        "city": "Helsinki",
        "postal_code": "00100",
        "country": "FIN",
        "latitude": "60.169857",
        "longitude": "24.938379",
        "invoice_base_url": "https://invoices.example.com",
        "invoice_creator": "CPO",
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

        assert terminal.customer_reference == "CUST-REF-001"
        assert terminal.address == "Street 1"
        assert terminal.city == "Helsinki"
        assert terminal.postal_code == "00100"
        assert terminal.country == "FIN"
        assert terminal.latitude == "60.169857"
        assert terminal.longitude == "24.938379"
        assert terminal.invoice_base_url == "https://invoices.example.com"
        assert terminal.invoice_creator == "CPO"

    def test_create_terminal_succeeds_with_only_terminal_id_no_identification_fields(
        self, terminal_service, credentialsrole
    ):
        terminal = terminal_service.create_terminal(
            {"terminal_id": "term-bare"}, credentialsrole
        )

        assert terminal.terminal_id == "term-bare"
        assert terminal.customer_reference is None
        assert terminal.party_id is None
        assert terminal.country_code is None

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
    def test_put_terminal_updates_terminal_successfully(
        self, terminal_service, credentialsrole
    ):
        location = LocationFactory(uid="LOC-PUT")
        evse = EvseFactory(uid="EVSE-PUT", location=location)

        terminal = TerminalFactory(
            terminal_id="terminal-put",
            credentials=credentialsrole.credentials,
            customer_reference="OLD-REF",
            invoice_base_url="https://old.com"
        )
        
        payload = TerminalIn(
            terminal_id="terminal-put",
            customer_reference="NEW-REF",
            invoice_base_url="https://example-url-for-invoices-new.com",
            location_uids=[location.uid],
            evse_uids=[evse.uid]
        )
        
        updated_terminal = terminal_service.put_terminal(terminal, payload)
        
        assert updated_terminal.customer_reference == "NEW-REF"
        assert updated_terminal.invoice_base_url == "https://example-url-for-invoices-new.com"
        assert list(updated_terminal.locations.all()) == [location]
        assert list(updated_terminal.evses.all()) == [evse]

    def test_patch_terminal_updates_only_provided_fields_successfully(
        self, terminal_service, credentialsrole
    ):
        location = LocationFactory(uid="LOC-PATCH")
        terminal = TerminalFactory(
            terminal_id="terminal-patch",
            credentials=credentialsrole.credentials,
            customer_reference="OLD-REF",
            invoice_base_url="https://example-url-for-invoices-old.com"
        )
        
        payload = TerminalIn(
            terminal_id="terminal-patch",
            customer_reference="PATCHED-REF",
            location_uids=[location.uid]
        )
        
        updated_terminal = terminal_service.patch_terminal(terminal, payload)
        
        assert updated_terminal.customer_reference == "PATCHED-REF"
        assert updated_terminal.invoice_base_url == "https://example-url-for-invoices-old.com"
        assert list(updated_terminal.locations.all()) == [location]
        assert list(updated_terminal.evses.all()) == []

    def test_put_terminal_raises_terminal_validation_error_when_provided_invalid_location(
        self, terminal_service, credentialsrole
    ):
        terminal = TerminalFactory(
            terminal_id="term-fail-put",
            credentials=credentialsrole.credentials
        )
        
        payload = TerminalIn(
            terminal_id="term-fail-put",
            location_uids=["NON-EXISTENT-LOC"]
        )
        
        with pytest.raises(TerminalValidationError) as exc_info:
            terminal_service.put_terminal(terminal, payload)
            
        assert "NON-EXISTENT-LOC" in str(exc_info.value)

    def test_patch_terminal_raises_terminal_validation_error_when_provided_invalid_evse(
        self, terminal_service, credentialsrole
    ):
        terminal = TerminalFactory(
            terminal_id="term-fail-patch",
            credentials=credentialsrole.credentials
        )
        
        payload = TerminalIn(
            terminal_id="term-fail-patch",
            evse_uids=["NON-EXISTENT-EVSE"]
        )
        
        with pytest.raises(TerminalValidationError) as exc_info:
            terminal_service.patch_terminal(terminal, payload)
            
        assert "NON-EXISTENT-EVSE" in str(exc_info.value)

    def test_validate_locations_raises_terminal_validation_error_when_provided_invalid_location(self, terminal_service):
        location = LocationFactory(uid="LOC-EXIST")
        
        with pytest.raises(TerminalValidationError) as exc_info:
            terminal_service._validate_locations([location.uid, "MISSING-LOC"])
            
        assert "MISSING-LOC" in str(exc_info.value)

    def test_validate_evses_raises_terminal_validation_error_when_provided_invalid_evse(self, terminal_service):
        location = LocationFactory(uid="LOC-E")
        evse = EvseFactory(uid="EVSE-EXIST", location=location)
        
        with pytest.raises(TerminalValidationError) as exc_info:
            terminal_service._validate_evses([evse.uid, "MISSING-EVSE"])
            
        assert "MISSING-EVSE" in str(exc_info.value)

    @patch("ocpi22.payments.services.send_ocpi_request")
    @patch("ocpi22.payments.services.get_our_party")
    @patch("ocpi22.payments.services.find_endpoints_by_roles")
    def test_send_to_ptp_sends_terminal_successfully(
        self, mock_find_endpoints, mock_get_party, mock_send, terminal_service, credentialsrole
    ):
        mock_find_endpoints.return_value = [("https://ptp.com/ocpi/payments", None, None, None, credentialsrole.credentials)]
        mock_party = type("OurParty", (), {"country_code": "FI", "party_id": "CPO"})
        mock_get_party.return_value = mock_party
        
        terminal = TerminalFactory(terminal_id="terminal001", credentials=credentialsrole.credentials)
        
        terminal_service._send_to_ptp(terminal, "patch", {"terminal_id": "terminal001", "location_ids": []})
        
        mock_send.apply_async.assert_called_once()
        kwargs = mock_send.apply_async.call_args[1]["kwargs"]
        assert kwargs["url"] == "https://ptp.com/ocpi/payments/terminals/terminal001"
        assert kwargs["method"] == "patch"
        assert kwargs["data"] == {"terminal_id": "terminal001", "location_ids": []}

    @patch("ocpi22.payments.services.send_ocpi_request")
    def test_send_to_ptp_does_not_send_request_when_no_credentials_found(self, mock_send, terminal_service):
        terminal = TerminalFactory(terminal_id="terminal-no-credentials", credentials=None)
        
        terminal_service._send_to_ptp(terminal, "put", {})
        
        mock_send.apply_async.assert_not_called()

    @patch("ocpi22.payments.services.send_ocpi_request")
    def test_send_to_ptp_does_not_send_request_when_no_role_found(self, mock_send, terminal_service, credentialsrole):
        credentialsrole.delete()
        terminal = TerminalFactory(terminal_id="terminal-no-role", credentials=credentialsrole.credentials)
        
        terminal_service._send_to_ptp(terminal, "put", {})
        
        mock_send.apply_async.assert_not_called()

    @patch("ocpi22.payments.services.send_ocpi_request")
    @patch("ocpi22.payments.services.find_endpoints_by_roles")
    def test_send_to_ptp_does_not_send_request_when_no_endpoint_found(
        self, mock_find_endpoints, mock_send, terminal_service, credentialsrole
    ):
        mock_find_endpoints.return_value = []
        terminal = TerminalFactory(terminal_id="terminal-no-endpoints", credentials=credentialsrole.credentials)
        
        terminal_service._send_to_ptp(terminal, "put", {})
        
        mock_send.apply_async.assert_not_called()
