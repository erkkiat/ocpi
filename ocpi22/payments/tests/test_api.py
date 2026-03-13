import base64
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from ocpi22.choices import OcpiRolesEnum
from ocpi22.payments.models import Terminal, FinancialAdviceConfirmation
from ocpi22.tests.factories import (
    CredentialsFactory,
    CredentialsRoleFactory,
    TerminalFactory,
    FinancialAdviceConfirmationFactory,
    LocationFactory,
    EvseFactory,
)

TERMINALS_URL = "/ocpi/2.2.1/payments/terminals"
FACS_URL = "/ocpi/2.2.1/payments/financial-advice-confirmations"


@pytest.fixture
def ptp_credentials():
    return CredentialsFactory()


@pytest.fixture
def ptp_credentialsrole(ptp_credentials):
    return CredentialsRoleFactory(
        role=OcpiRolesEnum.PTP,
        country_code="NL",
        party_id="PAY",
        credentials=ptp_credentials,
    )


@pytest.fixture
def other_ptp_credentials():
    return CredentialsFactory()


@pytest.fixture
def other_ptp_credentialsrole(other_ptp_credentials):
    return CredentialsRoleFactory(
        role=OcpiRolesEnum.PTP,
        country_code="DE",
        party_id="OTH",
        credentials=other_ptp_credentials,
    )


@pytest.fixture
def cpo_credentials():
    return CredentialsFactory()


@pytest.fixture
def cpo_credentialsrole(cpo_credentials):
    return CredentialsRoleFactory(
        role=OcpiRolesEnum.CPO,
        country_code="FI",
        party_id="CPO",
        credentials=cpo_credentials,
    )


@pytest.fixture
def ocpi_headers(ptp_credentials, ptp_credentialsrole):
    return {
        "HTTP_AUTHORIZATION": f"Token {base64.b64encode(ptp_credentials.ours.encode()).decode()}",
        "HTTP_OCPI_FROM_COUNTRY_CODE": "NL",
        "HTTP_OCPI_FROM_PARTY_ID": "PAY",
        "HTTP_OCPI_TO_COUNTRY_CODE": "FI",
        "HTTP_OCPI_TO_PARTY_ID": "CPO",
        "CONTENT_TYPE": "application/json",
    }


@pytest.fixture
def cpo_ocpi_headers(cpo_credentials, cpo_credentialsrole):
    return {
        "HTTP_AUTHORIZATION": f"Token {base64.b64encode(cpo_credentials.ours.encode()).decode()}",
        "HTTP_OCPI_FROM_COUNTRY_CODE": "FI",
        "HTTP_OCPI_FROM_PARTY_ID": "CPO",
        "HTTP_OCPI_TO_COUNTRY_CODE": "FI",
        "HTTP_OCPI_TO_PARTY_ID": "CPO",
        "CONTENT_TYPE": "application/json",
    }


@pytest.fixture
def valid_terminal_data():
    return {
        "terminal_id": "TERM-API-001",
        "customer_reference": "CUST-API-001",
        "last_updated": "2026-01-15T12:00:00Z",
    }


@pytest.fixture
def valid_terminal_data_with_coordinates():
    return {
        "terminal_id": "TERM-API-002",
        "customer_reference": "CUST-API-002",
        "coordinates": {"latitude": "52.372294", "longitude": "4.898632"},
        "address": "Keizersgracht 100",
        "city": "Amsterdam",
        "postal_code": "1015AA",
        "country": "NLD",
        "last_updated": "2026-01-15T12:00:00Z",
    }


@pytest.fixture
def valid_fac_data():
    return {
        "id": "FAC-API-001",
        "authorization_reference": "AUTH-API-001",
        "total_costs": {"excl_vat": 10.50, "incl_vat": 12.60},
        "currency": "EUR",
        "eft_data": ["EFT-001", "EFT-002"],
        "capture_status_code": "SUCCESS",
        "last_updated": timezone.now().isoformat(),
    }


@pytest.fixture
def db_terminal(ptp_credentialsrole):
    def _create(**kwargs):
        kwargs.setdefault("credentials", ptp_credentialsrole.credentials)
        return TerminalFactory(**kwargs)

    return _create


@pytest.fixture
def db_fac(ptp_credentialsrole):
    def _create(**kwargs):
        kwargs.setdefault("credentials", ptp_credentialsrole.credentials)
        return FinancialAdviceConfirmationFactory(**kwargs)

    return _create


@pytest.mark.django_db
class TestTerminalPostAPI:
    def test_post_terminal_creates_terminal_and_returns_201(
        self, client, ptp_credentialsrole, ocpi_headers, valid_terminal_data
    ):
        response = client.post(
            TERMINALS_URL, data=valid_terminal_data, format="json", **ocpi_headers
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["status_code"] == 1000
        assert body["status_message"] == "Success"
        assert "timestamp" in body
        assert body["data"]["terminal_id"] == "TERM-API-001"
        assert body["data"]["customer_reference"] == "CUST-API-001"
        assert body["data"]["location_ids"] == []
        assert body["data"]["evse_uids"] == []
        assert "last_updated" in body["data"]
        assert "coordinates" not in body["data"]
        assert Terminal.objects.filter(terminal_id="TERM-API-001").exists()

    def test_post_terminal_persists_with_correct_credentials(
        self, client, ptp_credentialsrole, ocpi_headers, valid_terminal_data
    ):
        client.post(
            TERMINALS_URL, data=valid_terminal_data, format="json", **ocpi_headers
        )

        terminal = Terminal.objects.get(terminal_id="TERM-API-001")
        assert terminal.credentials == ptp_credentialsrole.credentials

    def test_post_terminal_with_coordinates_persists_flat_fields(
        self,
        client,
        ptp_credentialsrole,
        ocpi_headers,
        valid_terminal_data_with_coordinates,
    ):
        response = client.post(
            TERMINALS_URL,
            data=valid_terminal_data_with_coordinates,
            format="json",
            **ocpi_headers,
        )

        assert response.status_code == status.HTTP_201_CREATED
        terminal = Terminal.objects.get(terminal_id="TERM-API-002")
        assert terminal.latitude == "52.372294"
        assert terminal.longitude == "4.898632"
        assert terminal.address == "Keizersgracht 100"
        assert terminal.city == "Amsterdam"
        assert terminal.postal_code == "1015AA"
        assert terminal.country == "NLD"

    def test_post_terminal_response_contains_nested_coordinates(
        self,
        client,
        ptp_credentialsrole,
        ocpi_headers,
        valid_terminal_data_with_coordinates,
    ):
        response = client.post(
            TERMINALS_URL,
            data=valid_terminal_data_with_coordinates,
            format="json",
            **ocpi_headers,
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["status_code"] == 1000
        assert body["status_message"] == "Success"
        assert "timestamp" in body
        assert body["data"]["terminal_id"] == "TERM-API-002"
        assert body["data"]["customer_reference"] == "CUST-API-002"
        assert body["data"]["coordinates"]["latitude"] == "52.372294"
        assert body["data"]["coordinates"]["longitude"] == "4.898632"
        assert body["data"]["address"] == "Keizersgracht 100"
        assert body["data"]["city"] == "Amsterdam"
        assert body["data"]["postal_code"] == "1015AA"
        assert body["data"]["country"] == "NLD"
        assert body["data"]["location_ids"] == []
        assert body["data"]["evse_uids"] == []
        assert "last_updated" in body["data"]

    def test_post_terminal_duplicate_returns_400(
        self,
        client,
        ptp_credentialsrole,
        ocpi_headers,
        valid_terminal_data,
        db_terminal,
    ):
        db_terminal(terminal_id="TERM-API-001")

        response = client.post(
            TERMINALS_URL, data=valid_terminal_data, format="json", **ocpi_headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert Terminal.objects.filter(terminal_id="TERM-API-001").count() == 1

    def test_post_terminal_with_globally_duplicate_terminal_id_returns_400(
        self,
        client,
        ptp_credentialsrole,
        other_ptp_credentialsrole,
        ocpi_headers,
        valid_terminal_data,
    ):
        TerminalFactory(
            terminal_id="TERM-API-001",
            credentials=other_ptp_credentialsrole.credentials,
        )

        response = client.post(
            TERMINALS_URL, data=valid_terminal_data, format="json", **ocpi_headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert Terminal.objects.filter(terminal_id="TERM-API-001").count() == 1

    def test_post_terminal_with_invalid_coordinates_returns_400(
        self, client, ptp_credentialsrole, ocpi_headers
    ):
        data = {
            "terminal_id": "TERM-BAD-001",
            "coordinates": {"latitude": "999.0", "longitude": "4.898632"},
        }

        response = client.post(TERMINALS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert not Terminal.objects.filter(terminal_id="TERM-BAD-001").exists()

    def test_post_terminal_without_auth_returns_401(self, client, valid_terminal_data):
        response = client.post(TERMINALS_URL, data=valid_terminal_data, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_post_terminal_with_cpo_role_returns_400(
        self, client, cpo_credentialsrole, cpo_ocpi_headers, valid_terminal_data
    ):
        response = client.post(
            TERMINALS_URL,
            data=valid_terminal_data,
            format="json",
            **cpo_ocpi_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert not Terminal.objects.filter(terminal_id="TERM-API-001").exists()


@pytest.mark.django_db
class TestTerminalGetAPI:
    def test_get_terminal_returns_200_with_terminal_data(
        self, client, ptp_credentialsrole, ocpi_headers, db_terminal
    ):
        db_terminal(terminal_id="TERM-GET-001", customer_reference="CUST-GET-001")

        response = client.get(f"{TERMINALS_URL}/TERM-GET-001", **ocpi_headers)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status_code"] == 1000
        assert body["status_message"] == "Success"
        assert "timestamp" in body
        assert body["data"]["terminal_id"] == "TERM-GET-001"
        assert body["data"]["customer_reference"] == "CUST-GET-001"
        assert body["data"]["location_ids"] == []
        assert body["data"]["evse_uids"] == []
        assert "last_updated" in body["data"]

    def test_get_terminal_returns_404_when_not_found(
        self, client, ptp_credentialsrole, ocpi_headers
    ):
        response = client.get(f"{TERMINALS_URL}/NONEXISTENT", **ocpi_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_terminal_returns_404_when_terminal_belongs_to_different_party(
        self,
        client,
        ptp_credentialsrole,
        other_ptp_credentialsrole,
        ocpi_headers,
    ):
        TerminalFactory(
            terminal_id="TERM-OTHER-001",
            credentials=other_ptp_credentialsrole.credentials,
        )

        response = client.get(f"{TERMINALS_URL}/TERM-OTHER-001", **ocpi_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_terminal_without_auth_returns_401(self, client, db_terminal):
        db_terminal(terminal_id="TERM-NOAUTH-001")

        response = client.get(f"{TERMINALS_URL}/TERM-NOAUTH-001")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_terminal_response_contains_coordinates_as_nested_object(
        self, client, ptp_credentialsrole, ocpi_headers, db_terminal
    ):
        db_terminal(
            terminal_id="TERM-COORD-001",
            latitude="60.169857",
            longitude="24.938379",
        )

        response = client.get(f"{TERMINALS_URL}/TERM-COORD-001", **ocpi_headers)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status_code"] == 1000
        assert body["status_message"] == "Success"
        assert "timestamp" in body
        assert body["data"]["terminal_id"] == "TERM-COORD-001"
        assert body["data"]["coordinates"]["latitude"] == "60.169857"
        assert body["data"]["coordinates"]["longitude"] == "24.938379"
        assert "last_updated" in body["data"]


@pytest.mark.django_db
class TestTerminalListAPI:
    def test_list_terminals_returns_200_with_empty_list(
        self, client, ptp_credentialsrole, ocpi_headers
    ):
        response = client.get(TERMINALS_URL, **ocpi_headers)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status_code"] == 1000
        assert "status_message" not in body
        assert "timestamp" in body
        assert body["data"] == []

    def test_list_terminals_returns_only_terminals_for_authenticated_party(
        self,
        client,
        ptp_credentialsrole,
        other_ptp_credentialsrole,
        ocpi_headers,
        db_terminal,
    ):
        db_terminal(
            terminal_id="TERM-MINE-001",
            customer_reference="CUST-MINE-001",
            address="Keizersgracht 100",
            city="Amsterdam",
            postal_code="1015AA",
            country="NLD",
            invoice_creator="PTP",
        )
        db_terminal(terminal_id="TERM-MINE-002")
        TerminalFactory(
            terminal_id="TERM-OTHER-001",
            credentials=other_ptp_credentialsrole.credentials,
        )

        response = client.get(TERMINALS_URL, **ocpi_headers)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status_code"] == 1000
        assert "status_message" not in body
        mine = next(t for t in body["data"] if t["terminal_id"] == "TERM-MINE-001")
        assert mine["customer_reference"] == "CUST-MINE-001"
        assert mine["address"] == "Keizersgracht 100"
        assert mine["city"] == "Amsterdam"
        assert mine["postal_code"] == "1015AA"
        assert mine["country"] == "NLD"
        assert mine["invoice_creator"] == "PTP"
        assert mine["location_ids"] == []
        assert mine["evse_uids"] == []
        assert "last_updated" in mine
        assert "coordinates" not in mine
        returned_ids = [t["terminal_id"] for t in body["data"]]
        assert "TERM-MINE-001" in returned_ids
        assert "TERM-MINE-002" in returned_ids
        assert "TERM-OTHER-001" not in returned_ids

    def test_list_terminals_without_auth_returns_401(self, client):
        response = client.get(TERMINALS_URL)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestFACPostAPI:
    def test_post_fac_creates_fac_and_returns_201(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        response = client.post(
            FACS_URL, data=valid_fac_data, format="json", **ocpi_headers
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["status_code"] == 1000
        assert body["status_message"] == "Success"
        assert "timestamp" in body
        assert body["data"]["id"] == "FAC-API-001"
        assert body["data"]["authorization_reference"] == "AUTH-API-001"
        assert body["data"]["total_costs"]["excl_vat"] == 10.50
        assert body["data"]["total_costs"]["incl_vat"] == 12.60
        assert body["data"]["currency"] == "EUR"
        assert body["data"]["eft_data"] == ["EFT-001", "EFT-002"]
        assert body["data"]["capture_status_code"] == "SUCCESS"
        assert "last_updated" in body["data"]
        assert "fac_id" not in body["data"]
        assert FinancialAdviceConfirmation.objects.filter(fac_id="FAC-API-001").exists()

    def test_post_fac_persists_with_correct_credentials(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        client.post(FACS_URL, data=valid_fac_data, format="json", **ocpi_headers)

        fac = FinancialAdviceConfirmation.objects.get(fac_id="FAC-API-001")
        assert fac.credentials == ptp_credentialsrole.credentials

    def test_post_fac_maps_spec_id_field_to_fac_id_model_field(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        client.post(FACS_URL, data=valid_fac_data, format="json", **ocpi_headers)

        assert FinancialAdviceConfirmation.objects.filter(fac_id="FAC-API-001").exists()

    def test_post_fac_response_uses_id_not_fac_id(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        response = client.post(
            FACS_URL, data=valid_fac_data, format="json", **ocpi_headers
        )

        body = response.json()
        assert body["data"]["id"] == "FAC-API-001"
        assert "fac_id" not in body["data"]

    def test_post_fac_response_has_nested_total_costs_with_currency_at_root(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        response = client.post(
            FACS_URL, data=valid_fac_data, format="json", **ocpi_headers
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["status_code"] == 1000
        assert body["status_message"] == "Success"
        assert "timestamp" in body
        assert body["data"]["id"] == "FAC-API-001"
        assert body["data"]["authorization_reference"] == "AUTH-API-001"
        assert body["data"]["total_costs"]["excl_vat"] == 10.50
        assert body["data"]["total_costs"]["incl_vat"] == 12.60
        assert body["data"]["currency"] == "EUR"
        assert "currency" not in body["data"]["total_costs"]
        assert body["data"]["eft_data"] == ["EFT-001", "EFT-002"]
        assert body["data"]["capture_status_code"] == "SUCCESS"
        assert "last_updated" in body["data"]

    def test_post_fac_links_terminal_when_terminal_id_provided(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data, db_terminal
    ):
        terminal = db_terminal(terminal_id="TERM-FOR-FAC-001")
        data = {**valid_fac_data, "terminal_id": "TERM-FOR-FAC-001"}

        response = client.post(FACS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["status_code"] == 1000
        assert body["status_message"] == "Success"
        assert "timestamp" in body
        assert body["data"]["id"] == "FAC-API-001"
        assert body["data"]["authorization_reference"] == "AUTH-API-001"
        assert body["data"]["total_costs"]["excl_vat"] == 10.50
        assert body["data"]["total_costs"]["incl_vat"] == 12.60
        assert body["data"]["currency"] == "EUR"
        assert body["data"]["eft_data"] == ["EFT-001", "EFT-002"]
        assert body["data"]["capture_status_code"] == "SUCCESS"
        assert "last_updated" in body["data"]
        fac = FinancialAdviceConfirmation.objects.get(fac_id="FAC-API-001")
        assert fac.terminal == terminal

    def test_post_fac_has_no_terminal_when_terminal_id_not_provided(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        response = client.post(
            FACS_URL, data=valid_fac_data, format="json", **ocpi_headers
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["status_code"] == 1000
        assert body["status_message"] == "Success"
        assert "timestamp" in body
        assert body["data"]["id"] == "FAC-API-001"
        assert body["data"]["authorization_reference"] == "AUTH-API-001"
        assert body["data"]["total_costs"]["excl_vat"] == 10.50
        assert body["data"]["total_costs"]["incl_vat"] == 12.60
        assert body["data"]["currency"] == "EUR"
        assert body["data"]["eft_data"] == ["EFT-001", "EFT-002"]
        assert body["data"]["capture_status_code"] == "SUCCESS"
        assert "last_updated" in body["data"]
        fac = FinancialAdviceConfirmation.objects.get(fac_id="FAC-API-001")
        assert fac.terminal is None

    def test_post_fac_returns_400_when_terminal_id_does_not_exist(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        data = {**valid_fac_data, "terminal_id": "NONEXISTENT-TERM"}

        response = client.post(FACS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert not FinancialAdviceConfirmation.objects.filter(
            fac_id="FAC-API-001"
        ).exists()

    def test_post_fac_returns_400_when_terminal_belongs_to_different_party(
        self,
        client,
        ptp_credentialsrole,
        other_ptp_credentialsrole,
        ocpi_headers,
        valid_fac_data,
    ):
        TerminalFactory(
            terminal_id="TERM-OTHER-PARTY",
            credentials=other_ptp_credentialsrole.credentials,
        )
        data = {**valid_fac_data, "terminal_id": "TERM-OTHER-PARTY"}

        response = client.post(FACS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert not FinancialAdviceConfirmation.objects.filter(
            fac_id="FAC-API-001"
        ).exists()

    def test_post_fac_duplicate_returns_400(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data, db_fac
    ):
        db_fac(fac_id="FAC-API-001")

        response = client.post(
            FACS_URL, data=valid_fac_data, format="json", **ocpi_headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert (
            FinancialAdviceConfirmation.objects.filter(fac_id="FAC-API-001").count()
            == 1
        )

    def test_post_fac_with_missing_total_costs_returns_400(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        data = {k: v for k, v in valid_fac_data.items() if k != "total_costs"}

        response = client.post(FACS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert not FinancialAdviceConfirmation.objects.filter(
            fac_id="FAC-API-001"
        ).exists()

    def test_post_fac_with_missing_currency_returns_400(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        data = {k: v for k, v in valid_fac_data.items() if k != "currency"}

        response = client.post(FACS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert not FinancialAdviceConfirmation.objects.filter(
            fac_id="FAC-API-001"
        ).exists()

    def test_post_fac_without_auth_returns_401(self, client, valid_fac_data):
        response = client.post(FACS_URL, data=valid_fac_data, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_post_fac_with_cpo_role_returns_400(
        self, client, cpo_credentialsrole, cpo_ocpi_headers, valid_fac_data
    ):
        response = client.post(
            FACS_URL, data=valid_fac_data, format="json", **cpo_ocpi_headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert not FinancialAdviceConfirmation.objects.filter(
            fac_id="FAC-API-001"
        ).exists()

    @pytest.mark.parametrize(
        "capture_status_code", ["SUCCESS", "PARTIAL_SUCCESS", "FAILED"]
    )
    def test_post_fac_accepts_all_valid_capture_status_codes(
        self,
        client,
        ptp_credentialsrole,
        ocpi_headers,
        valid_fac_data,
        capture_status_code,
    ):
        data = {
            **valid_fac_data,
            "id": f"FAC-STATUS-{capture_status_code}",
            "capture_status_code": capture_status_code,
        }

        response = client.post(FACS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["status_code"] == 1000
        assert body["status_message"] == "Success"
        assert "timestamp" in body
        assert body["data"]["id"] == f"FAC-STATUS-{capture_status_code}"
        assert body["data"]["capture_status_code"] == capture_status_code
        assert FinancialAdviceConfirmation.objects.filter(
            fac_id=f"FAC-STATUS-{capture_status_code}",
            capture_status_code=capture_status_code,
        ).exists()


@pytest.mark.django_db
class TestFACGetAPI:
    def test_get_fac_returns_200_with_fac_data(
        self, client, ptp_credentialsrole, ocpi_headers, db_fac
    ):
        db_fac(
            fac_id="FAC-GET-001",
            authorization_reference="AUTH-GET-001",
            total_cost_excl_vat=10.0,
            total_cost_incl_vat=12.4,
            currency="EUR",
            eft_data=["EFT-DATA-001", "EFT-DATA-002"],
            capture_status_code="SUCCESS",
            capture_status_message="Capture successful at PSP",
        )

        response = client.get(f"{FACS_URL}/FAC-GET-001", **ocpi_headers)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status_code"] == 1000
        assert body["status_message"] == "Success"
        assert "timestamp" in body
        assert body["data"]["id"] == "FAC-GET-001"
        assert body["data"]["authorization_reference"] == "AUTH-GET-001"
        assert body["data"]["total_costs"]["excl_vat"] == 10.0
        assert body["data"]["total_costs"]["incl_vat"] == 12.4
        assert body["data"]["currency"] == "EUR"
        assert body["data"]["eft_data"] == ["EFT-DATA-001", "EFT-DATA-002"]
        assert body["data"]["capture_status_code"] == "SUCCESS"
        assert body["data"]["capture_status_message"] == "Capture successful at PSP"
        assert "last_updated" in body["data"]
        assert "fac_id" not in body["data"]

    def test_get_fac_response_uses_id_not_fac_id(
        self, client, ptp_credentialsrole, ocpi_headers, db_fac
    ):
        db_fac(fac_id="FAC-GET-002")

        response = client.get(f"{FACS_URL}/FAC-GET-002", **ocpi_headers)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status_code"] == 1000
        assert body["status_message"] == "Success"
        assert "timestamp" in body
        assert body["data"]["id"] == "FAC-GET-002"
        assert "fac_id" not in body["data"]

    def test_get_fac_returns_404_when_not_found(
        self, client, ptp_credentialsrole, ocpi_headers
    ):
        response = client.get(f"{FACS_URL}/NONEXISTENT", **ocpi_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_fac_returns_404_when_fac_belongs_to_different_party(
        self,
        client,
        ptp_credentialsrole,
        other_ptp_credentialsrole,
        ocpi_headers,
    ):
        FinancialAdviceConfirmationFactory(
            fac_id="FAC-OTHER-001",
            credentials=other_ptp_credentialsrole.credentials,
        )

        response = client.get(f"{FACS_URL}/FAC-OTHER-001", **ocpi_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_fac_without_auth_returns_401(self, client, db_fac):
        db_fac(fac_id="FAC-NOAUTH-001")

        response = client.get(f"{FACS_URL}/FAC-NOAUTH-001")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_fac_response_has_nested_total_costs_with_currency_at_root(
        self, client, ptp_credentialsrole, ocpi_headers, db_fac
    ):
        db_fac(
            fac_id="FAC-COSTS-001",
            authorization_reference="AUTH-COSTS-001",
            total_cost_excl_vat=25.00,
            total_cost_incl_vat=31.00,
            currency="NOK",
            eft_data=["EFT-NOK-001"],
            capture_status_code="SUCCESS",
        )

        response = client.get(f"{FACS_URL}/FAC-COSTS-001", **ocpi_headers)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status_code"] == 1000
        assert body["status_message"] == "Success"
        assert "timestamp" in body
        assert body["data"]["id"] == "FAC-COSTS-001"
        assert body["data"]["authorization_reference"] == "AUTH-COSTS-001"
        assert body["data"]["total_costs"]["excl_vat"] == 25.00
        assert body["data"]["total_costs"]["incl_vat"] == 31.00
        assert body["data"]["currency"] == "NOK"
        assert "currency" not in body["data"]["total_costs"]
        assert body["data"]["eft_data"] == ["EFT-NOK-001"]
        assert body["data"]["capture_status_code"] == "SUCCESS"
        assert "last_updated" in body["data"]


@pytest.mark.django_db
class TestFACListAPI:
    def test_list_facs_returns_200_with_empty_list(
        self, client, ptp_credentialsrole, ocpi_headers
    ):
        response = client.get(FACS_URL, **ocpi_headers)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status_code"] == 1000
        assert "status_message" not in body
        assert "timestamp" in body
        assert body["data"] == []

    def test_list_facs_returns_only_facs_for_authenticated_party(
        self,
        client,
        ptp_credentialsrole,
        other_ptp_credentialsrole,
        ocpi_headers,
        db_fac,
    ):
        db_fac(
            fac_id="FAC-MINE-001",
            authorization_reference="AUTH-MINE-001",
            total_cost_excl_vat=10.0,
            total_cost_incl_vat=12.4,
            currency="EUR",
            eft_data=["EFT-DATA-001", "EFT-DATA-002"],
            capture_status_code="SUCCESS",
        )
        db_fac(fac_id="FAC-MINE-002")
        FinancialAdviceConfirmationFactory(
            fac_id="FAC-OTHER-001",
            credentials=other_ptp_credentialsrole.credentials,
        )

        response = client.get(FACS_URL, **ocpi_headers)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status_code"] == 1000
        assert "status_message" not in body
        mine = next(f for f in body["data"] if f["id"] == "FAC-MINE-001")
        assert mine["authorization_reference"] == "AUTH-MINE-001"
        assert mine["total_costs"]["excl_vat"] == 10.0
        assert mine["total_costs"]["incl_vat"] == 12.4
        assert mine["currency"] == "EUR"
        assert mine["eft_data"] == ["EFT-DATA-001", "EFT-DATA-002"]
        assert mine["capture_status_code"] == "SUCCESS"
        assert mine["capture_status_message"] is None
        assert "last_updated" in mine
        assert "fac_id" not in mine
        returned_ids = [f["id"] for f in body["data"]]
        assert "FAC-MINE-001" in returned_ids
        assert "FAC-MINE-002" in returned_ids
        assert "FAC-OTHER-001" not in returned_ids

    def test_list_facs_without_auth_returns_401(self, client):
        response = client.get(FACS_URL)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestTerminalPostEdgeCases:
    def test_post_terminal_without_terminal_id_returns_400(
        self, client, ptp_credentialsrole, ocpi_headers
    ):
        response = client.post(
            TERMINALS_URL,
            data={"customer_reference": "CUST-NO-ID"},
            format="json",
            **ocpi_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert not Terminal.objects.filter(customer_reference="CUST-NO-ID").exists()

    def test_post_terminal_with_partial_coordinates_missing_longitude_returns_400(
        self, client, ptp_credentialsrole, ocpi_headers
    ):
        data = {
            "terminal_id": "TERM-PARTIAL-COORD",
            "coordinates": {"latitude": "60.169857"},
        }

        response = client.post(TERMINALS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert not Terminal.objects.filter(terminal_id="TERM-PARTIAL-COORD").exists()

    def test_post_terminal_with_partial_coordinates_missing_latitude_returns_400(
        self, client, ptp_credentialsrole, ocpi_headers
    ):
        data = {
            "terminal_id": "TERM-PARTIAL-LAT",
            "coordinates": {"longitude": "24.938379"},
        }

        response = client.post(TERMINALS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert not Terminal.objects.filter(terminal_id="TERM-PARTIAL-LAT").exists()

    def test_post_terminal_response_has_no_coordinates_key_when_no_coordinates_provided(
        self, client, ptp_credentialsrole, ocpi_headers
    ):
        response = client.post(
            TERMINALS_URL,
            data={
                "terminal_id": "TERM-NO-COORD",
                "customer_reference": "CUST-NO-COORD",
                "last_updated": "2026-01-15T12:00:00Z",
            },
            format="json",
            **ocpi_headers,
        )

        body = response.json()
        assert response.status_code == status.HTTP_201_CREATED
        assert body["status_code"] == 1000
        assert "timestamp" in body
        assert "coordinates" not in body["data"]

    def test_post_terminal_with_null_coordinates_returns_201_without_coordinates(
        self, client, ptp_credentialsrole, ocpi_headers
    ):
        data = {
            "terminal_id": "TERM-NULL-COORD",
            "customer_reference": "CUST-NULL-COORD",
            "coordinates": None,
            "last_updated": "2026-01-15T12:00:00Z",
        }

        response = client.post(TERMINALS_URL, data=data, format="json", **ocpi_headers)

        body = response.json()
        assert response.status_code == status.HTTP_201_CREATED
        assert body["status_code"] == 1000
        assert "timestamp" in body
        assert "coordinates" not in body["data"]

    def test_post_terminal_response_includes_empty_location_ids_and_evse_uids(
        self, client, ptp_credentialsrole, ocpi_headers
    ):
        response = client.post(
            TERMINALS_URL,
            data={
                "terminal_id": "TERM-LOC-FIELDS",
                "customer_reference": "CUST-LOC-FIELDS",
                "last_updated": "2026-01-15T12:00:00Z",
            },
            format="json",
            **ocpi_headers,
        )

        body = response.json()
        assert response.status_code == status.HTTP_201_CREATED
        assert body["status_code"] == 1000
        assert "timestamp" in body
        assert body["data"]["location_ids"] == []
        assert body["data"]["evse_uids"] == []


@pytest.mark.django_db
class TestFACPostEdgeCases:
    def test_post_fac_without_incl_vat_returns_201(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        data = {
            **valid_fac_data,
            "id": "FAC-NO-INCLVAT",
            "total_costs": {"excl_vat": 8.00},
        }

        response = client.post(FACS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["status_code"] == 1000
        assert body["status_message"] == "Success"
        assert "timestamp" in body
        assert body["data"]["id"] == "FAC-NO-INCLVAT"
        assert body["data"]["authorization_reference"] == "AUTH-API-001"
        assert body["data"]["total_costs"]["excl_vat"] == 8.00
        assert body["data"]["currency"] == "EUR"
        assert body["data"]["eft_data"] == ["EFT-001", "EFT-002"]
        assert body["data"]["capture_status_code"] == "SUCCESS"
        assert "last_updated" in body["data"]
        fac = FinancialAdviceConfirmation.objects.get(fac_id="FAC-NO-INCLVAT")
        assert fac.total_cost_incl_vat is None

    def test_post_fac_response_omits_incl_vat_when_not_provided(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        data = {
            **valid_fac_data,
            "id": "FAC-OMIT-INCLVAT",
            "total_costs": {"excl_vat": 8.00},
        }

        response = client.post(FACS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["status_code"] == 1000
        assert body["status_message"] == "Success"
        assert "timestamp" in body
        assert body["data"]["id"] == "FAC-OMIT-INCLVAT"
        assert body["data"]["authorization_reference"] == "AUTH-API-001"
        assert body["data"]["total_costs"]["excl_vat"] == 8.00
        assert "incl_vat" not in body["data"]["total_costs"]
        assert body["data"]["currency"] == "EUR"
        assert body["data"]["eft_data"] == ["EFT-001", "EFT-002"]
        assert body["data"]["capture_status_code"] == "SUCCESS"
        assert "last_updated" in body["data"]

    def test_post_fac_with_invalid_capture_status_code_returns_400(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        data = {
            **valid_fac_data,
            "id": "FAC-BAD-STATUS",
            "capture_status_code": "INVALID_CODE",
        }

        response = client.post(FACS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert not FinancialAdviceConfirmation.objects.filter(
            fac_id="FAC-BAD-STATUS"
        ).exists()

    def test_post_fac_with_invalid_currency_code_returns_400(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        data = {**valid_fac_data, "id": "FAC-BAD-CURRENCY", "currency": "INVALID"}

        response = client.post(FACS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert not FinancialAdviceConfirmation.objects.filter(
            fac_id="FAC-BAD-CURRENCY"
        ).exists()

    def test_post_fac_without_id_returns_400(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        data = {k: v for k, v in valid_fac_data.items() if k != "id"}

        response = client.post(FACS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body

    def test_post_fac_without_authorization_reference_returns_400(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        data = {
            k: v for k, v in valid_fac_data.items() if k != "authorization_reference"
        }

        response = client.post(FACS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert not FinancialAdviceConfirmation.objects.filter(
            fac_id="FAC-API-001"
        ).exists()

    def test_post_fac_without_last_updated_returns_400(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        data = {k: v for k, v in valid_fac_data.items() if k != "last_updated"}

        response = client.post(FACS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert not FinancialAdviceConfirmation.objects.filter(
            fac_id="FAC-API-001"
        ).exists()

    def test_post_fac_with_empty_eft_data_returns_400(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        data = {**valid_fac_data, "id": "FAC-EMPTY-EFT", "eft_data": []}

        response = client.post(FACS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert not FinancialAdviceConfirmation.objects.filter(
            fac_id="FAC-EMPTY-EFT"
        ).exists()

    def test_post_fac_with_negative_excl_vat_returns_400(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        data = {
            **valid_fac_data,
            "id": "FAC-NEG-EXCL",
            "total_costs": {"excl_vat": -1.00, "incl_vat": -0.50},
        }

        response = client.post(FACS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert not FinancialAdviceConfirmation.objects.filter(
            fac_id="FAC-NEG-EXCL"
        ).exists()

    def test_post_fac_with_incl_vat_less_than_excl_vat_returns_400(
        self, client, ptp_credentialsrole, ocpi_headers, valid_fac_data
    ):
        data = {
            **valid_fac_data,
            "id": "FAC-VAT-INVALID",
            "total_costs": {"excl_vat": 20.00, "incl_vat": 10.00},
        }

        response = client.post(FACS_URL, data=data, format="json", **ocpi_headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert not FinancialAdviceConfirmation.objects.filter(
            fac_id="FAC-VAT-INVALID"
        ).exists()

    def test_post_fac_with_cross_party_duplicate_fac_id_returns_400(
        self,
        client,
        ptp_credentialsrole,
        other_ptp_credentialsrole,
        ocpi_headers,
        valid_fac_data,
    ):
        FinancialAdviceConfirmationFactory(
            fac_id="FAC-API-001",
            credentials=other_ptp_credentialsrole.credentials,
        )

        response = client.post(
            FACS_URL, data=valid_fac_data, format="json", **ocpi_headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["status_code"] == 2001
        assert "timestamp" in body
        assert (
            FinancialAdviceConfirmation.objects.filter(fac_id="FAC-API-001").count()
            == 1
        )


@pytest.mark.django_db
class TestTerminalGetEdgeCases:
    def test_get_terminal_response_has_no_coordinates_when_lat_lon_null(
        self, client, ptp_credentialsrole, ocpi_headers, db_terminal
    ):
        db_terminal(terminal_id="TERM-NO-LATLON", latitude=None, longitude=None)

        response = client.get(f"{TERMINALS_URL}/TERM-NO-LATLON", **ocpi_headers)

        data = response.json()
        assert response.status_code == status.HTTP_200_OK
        assert "coordinates" not in data["data"]

    def test_get_terminal_response_includes_location_ids_and_evse_uids(
        self, client, ptp_credentialsrole, ocpi_headers, db_terminal
    ):
        db_terminal(terminal_id="TERM-WITH-LOCS")

        response = client.get(f"{TERMINALS_URL}/TERM-WITH-LOCS", **ocpi_headers)

        data = response.json()["data"]
        assert response.status_code == status.HTTP_200_OK
        assert data["location_ids"] == []
        assert data["evse_uids"] == []


@pytest.mark.django_db
class TestListPaginationHeaders:
    def test_list_terminals_response_includes_x_total_count_header(
        self, client, ptp_credentialsrole, ocpi_headers, db_terminal
    ):
        db_terminal(terminal_id="TERM-PAGE-001")
        db_terminal(terminal_id="TERM-PAGE-002")

        response = client.get(TERMINALS_URL, **ocpi_headers)

        assert response.status_code == status.HTTP_200_OK
        assert "X-Total-Count" in response

    def test_list_facs_response_includes_x_total_count_header(
        self, client, ptp_credentialsrole, ocpi_headers, db_fac
    ):
        db_fac(fac_id="FAC-PAGE-001")
        db_fac(fac_id="FAC-PAGE-002")

        response = client.get(FACS_URL, **ocpi_headers)

        assert response.status_code == status.HTTP_200_OK
        assert "X-Total-Count" in response


PAYMENTS_ROOT_URL = "/ocpi/2.2.1/payments/"


@pytest.mark.django_db
class TestPaymentsRootView:
    def test_get_payments_root_returns_405(
        self, client, ptp_credentialsrole, ocpi_headers
    ):
        response = client.get(PAYMENTS_ROOT_URL, **ocpi_headers)

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_get_payments_root_returns_ocpi_error_status_code(
        self, client, ptp_credentialsrole, ocpi_headers
    ):
        response = client.get(PAYMENTS_ROOT_URL, **ocpi_headers)

        body = response.json()
        assert body["status_code"] == 2000

    def test_get_payments_root_without_auth_returns_401(self, client):
        response = client.get(PAYMENTS_ROOT_URL)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.fixture
def location():
    location = LocationFactory(uid="LOC-123")
    EvseFactory(uid="EVSE-123", location=location)
    return location


@pytest.mark.django_db
class TestCPOTerminalAPI:
    @pytest.mark.parametrize(
        "api_client, expected_status_code",
        [
            pytest.param("client", 401, id="Unauthenticated user getting unauthorized"),
            pytest.param(
                "authenticated_user_client",
                200,
                id="Authenticated user can access terminals api",
            ),
            pytest.param(
                "admin_user_client", 200, id="Admin user can access terminals api"
            ),
            pytest.param(
                "super_user_client", 200, id="Super user can access terminals api"
            ),
        ],
    )
    def test_put_terminal_with_proper_credentials(
        self, api_client, expected_status_code, request, db_terminal, location
    ):
        terminal = db_terminal(terminal_id="TERM-AUTH-001")
        payload = {
            "terminal_id": terminal.terminal_id,
            "location_uids": [location.uid],
            "evse_uids": [location.evses.first().uid],
        }

        test_client = request.getfixturevalue(api_client)
        url = reverse("payments:put_terminal")
        response = test_client.put(url, payload, format="json")

        assert response.status_code == expected_status_code

    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_update_terminal_with_no_terminal_id_returns_422(
        self, authenticated_user_client, method
    ):
        payload = {
            "location_uids": ["LOC-123"],
            "evse_uids": ["EVSE-123"],
        }

        url = reverse(f"payments:{method}_terminal")
        function = getattr(authenticated_user_client, method.lower(), None)
        response = function(url, payload, format="json")

        assert response.status_code == 422

    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_update_terminal_with_empty_location_or_evse_list_returns_422(
        self, authenticated_user_client, method
    ):
        payload = {
            "terminal_id": "TERM-001",
            "location_uids": None,
            "evse_uids": None,
        }

        url = reverse(f"payments:{method}_terminal")
        function = getattr(authenticated_user_client, method.lower(), None)
        response = function(url, payload, format="json")

        assert response.status_code == 422

    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_update_terminal_with_invalid_location_or_evse_uids_returns_422(
        self, authenticated_user_client, db_terminal, method
    ):
        terminal = db_terminal(terminal_id="TERM-INVALID-UIDS")
        payload = {
            "terminal_id": terminal.terminal_id,
            "location_uids": ["NON-EXISTENT-LOC"],
            "evse_uids": ["NON-EXISTENT-EVSE"],
        }

        url = reverse(f"payments:{method}_terminal")
        function = getattr(authenticated_user_client, method.lower(), None)
        response = function(url, payload, format="json")

        assert response.status_code == 422
        assert "invalid" in response.json().get("message", "").lower()

    @patch("ocpi22.payments.services.send_ocpi_request")
    def test_put_terminal_locations_updates_database_and_calls_ptp(
        self, mock_send_ocpi_request, authenticated_user_client, db_terminal, location
    ):
        terminal = db_terminal(terminal_id="TERM-001")
        terminal.credentials.url = "https://example.com/ocpi/cpo/2.2/"
        terminal.credentials.save()
        terminal.credentials.refresh_from_db()

        evse = location.evses.first()

        payload = {
            "terminal_id": terminal.terminal_id,
            "location_uids": [location.uid],
            "evse_uids": [evse.uid],
        }

        assert terminal.locations.count() == 0
        assert terminal.evses.count() == 0

        url = reverse("payments:put_terminal")
        response = authenticated_user_client.put(url, payload, format="json")

        assert response.status_code == 200
        data = response.json()
        assert data["location_ids"] == [location.uid]
        assert data["evse_uids"] == [location.evses.first().uid]

        terminal.refresh_from_db()
        assert terminal.locations.count() == 1
        assert terminal.locations.first() == location
        assert terminal.evses.count() == 1
        assert terminal.evses.first() == location.evses.first()

        mock_send_ocpi_request.apply_async.assert_called_once()
        kwargs = mock_send_ocpi_request.apply_async.call_args[1]["kwargs"]
        assert kwargs["url"] == "https://localhost/ocpi/payments/terminals/TERM-001"
        assert kwargs["method"] == "put"
        assert kwargs["data"]["location_uids"] == [location.uid]
        assert kwargs["to_party_id"] == "PAY"

    @patch("ocpi22.payments.services.send_ocpi_request")
    def test_patch_terminal_locations_updates_db_and_calls_external_api(
        self, mock_send_ocpi_request, authenticated_user_client, db_terminal, location
    ):
        terminal = db_terminal(terminal_id="TERM-002")
        terminal.credentials.url = "https://example.com/ocpi/cpo/2.2/"
        terminal.credentials.save()
        terminal.credentials.refresh_from_db()

        payload = {
            "terminal_id": terminal.terminal_id,
            "location_uids": [location.uid],
        }

        url = reverse("payments:patch_terminal")
        response = authenticated_user_client.patch(url, payload, format="json")

        assert response.status_code == 200
        data = response.json()
        assert data["location_ids"] == [location.uid]
        assert data["evse_uids"] == []

        terminal.refresh_from_db()
        assert terminal.locations.count() == 1
        assert terminal.locations.first() == location
        assert terminal.evses.count() == 0

        mock_send_ocpi_request.apply_async.assert_called_once()
        kwargs = mock_send_ocpi_request.apply_async.call_args[1]["kwargs"]
        assert kwargs["url"] == "https://localhost/ocpi/payments/terminals/TERM-002"
        assert kwargs["method"] == "patch"
        assert kwargs["data"]["location_uids"] == [location.uid]
