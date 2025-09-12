import pytest
from datetime import datetime
from django.conf import settings

from integrations.hubject.oicp_to_ocpi_converter import (
    map_successful_oicp_authorization_response_to_ocpi_221,
)


class TestMapOICPAuthorizationResponseToOCPI221:
    @pytest.mark.asyncio
    @pytest.mark.django_db
    def test_successful_mapping_with_valid_response(self):
        """Test that a valid OICP authorization response is correctly mapped to OCPI format"""
        token_id = "TEST123456"
        oicp_response = {
            "AuthorizationStatus": "Authorized",
            "ProviderID": "FI-MSP",
            "StatusCode": {"Code": "000"},
            "SessionID": "HUBJECT-SESSION-1234",
            "EMPPartnerSessionID": "MSP-AUTHORIZATION-5678",
        }

        result = map_successful_oicp_authorization_response_to_ocpi_221(
            oicp_response, token_id
        )

        assert result is not None
        assert "data" in result

        data = result["data"]
        assert data["allowed"] == "ALLOWED"
        assert data["authorization_reference"] == "MSP-AUTHORIZATION-5678"
        assert data["hub_session_id"] == "HUBJECT-SESSION-1234"

        token = data["token"]
        assert token["uid"] == token_id
        assert token["country_code"] == "FI"
        assert token["party_id"] == "MSP"
        assert token["issuer"] == "FI*MSP"
        assert token["language"] == settings.LANGUAGE_CODE.upper()
        assert token["type"] == "RFID"
        assert token["valid"] is True
        assert token["whitelist"] == "NEVER"
        assert token["default_profile_type"] == "REGULAR"
        assert token["contract_id"] == "N/A"

        assert "last_updated" in token
        try:
            datetime.strptime(token["last_updated"], settings.OCPI_DATE_FORMAT)
        except ValueError:
            pytest.fail("last_updated field is not in the correct date format")

    def test_mapping_with_provider_id_none_results_in_none_ocpi_221_response(self):
        token_id = "TEST123456"
        oicp_response = {
            "AuthorizationStatus": "Authorized",
            "ProviderID": None,
            "StatusCode": {"Code": "000"},
            "SessionID": "HUBJECT-SESSION-1234",
            "EMPPartnerSessionID": "DE*ICE",
        }

        result = map_successful_oicp_authorization_response_to_ocpi_221(
            oicp_response, token_id
        )
        assert result is None

    def test_mapping_with_authorization_status_none_results_in_hubject_emp_id(self):
        token_id = "TEST123456"
        oicp_response = {
            "AuthorizationStatus": "Authorized",
            "ProviderID": "FI*MSP",
            "StatusCode": {"Code": "000"},
            "SessionID": "HUBJECT-SESSION-1234",
            "EMPPartnerSessionID": None,
        }

        result = map_successful_oicp_authorization_response_to_ocpi_221(
            oicp_response, token_id
        )
        assert result is not None
        assert "data" in result

        data = result["data"]
        assert data["authorization_reference"] == settings.HUBJECT_EMP_ID

    def test_mapping_with_different_authorization_status_results_in_not_allowed(
        self,
    ):
        token_id = "TEST123456"
        oicp_response = {
            "AuthorizationStatus": "SomeOtherStatus",  # Not "Authorized"
            "ProviderID": "FIMSP",
            "StatusCode": {"Code": "000"},
            "SessionID": "HUBJECT-SESSION-1234",
        }

        result = map_successful_oicp_authorization_response_to_ocpi_221(
            oicp_response, token_id
        )

        assert result is not None
        assert result["data"]["allowed"] == "NOT_ALLOWED"
        assert result["data"]["authorization_reference"] == settings.HUBJECT_EMP_ID
        assert result["data"]["hub_session_id"] == "HUBJECT-SESSION-1234"

    def test_mapping_with_complex_provider_id_succeeds(self):
        token_id = "TEST123456"
        oicp_response = {
            "AuthorizationStatus": "Authorized",
            "ProviderID": "DE*COMPLEX123",
            "StatusCode": {"Code": "000"},
            "SessionID": "HUBJECT-SESSION-1234",
        }

        result = map_successful_oicp_authorization_response_to_ocpi_221(
            oicp_response, token_id
        )

        assert result is not None
        assert result["data"]["token"]["country_code"] == "DE"
        assert result["data"]["token"]["party_id"] == "COMPLEX123"
        assert result["data"]["token"]["issuer"] == "DE*COMPLEX123"

    def test_mapping_with_failed_status_code_succeeds(self):
        """Test mapping with a non-success status code"""
        token_id = "TEST123456"
        oicp_response = {
            "AuthorizationStatus": "Authorized",
            "ProviderID": "FI*MSP",
            "StatusCode": {"Code": "100"},  # Not a success code
            "SessionID": "HUBJECT-SESSION-1234",
        }

        result = map_successful_oicp_authorization_response_to_ocpi_221(
            oicp_response, token_id
        )
        assert result["data"]["authorization_reference"] == settings.HUBJECT_EMP_ID
        assert result["data"]["hub_session_id"] == "HUBJECT-SESSION-1234"
        assert result["data"]["allowed"] == "ALLOWED"

    def test_mapping_with_missing_authorization_status_fails(self):
        """Test mapping when AuthorizationStatus is missing"""
        token_id = "TEST123456"
        oicp_response = {
            # No AuthorizationStatus
            "ProviderID": "FI*MSP",
            "StatusCode": {"Code": "000"},
            "SessionID": "HUBJECT-SESSION-1234",
        }

        with pytest.raises(KeyError):
            map_successful_oicp_authorization_response_to_ocpi_221(
                oicp_response, token_id
            )

    def test_mapping_with_missing_status_code_succeeds(self):
        """Test mapping when StatusCode is missing"""
        token_id = "TEST123456"
        oicp_response = {
            "AuthorizationStatus": "Authorized",
            "ProviderID": "FI*MSP",
            # No StatusCode
            "SessionID": "HUBJECT-SESSION-1234",
        }

        result = map_successful_oicp_authorization_response_to_ocpi_221(
            oicp_response, token_id
        )
        assert result["data"]["authorization_reference"] == settings.HUBJECT_EMP_ID
        assert result["data"]["hub_session_id"] == "HUBJECT-SESSION-1234"
        assert result["data"]["allowed"] == "ALLOWED"

    def test_mapping_with_missing_provider_id_fails(self):
        """Test mapping when ProviderID is missing"""
        token_id = "TEST123456"
        oicp_response = {
            "AuthorizationStatus": "Authorized",
            # No ProviderID
            "StatusCode": {"Code": "000"},
            "SessionID": "HUBJECT-SESSION-1234",
        }

        result = map_successful_oicp_authorization_response_to_ocpi_221(
            oicp_response, token_id
        )
        assert result is None

    def test_mapping_with_empty_response_results_in_not_allowed(self):
        token_id = "TEST123456"
        oicp_response = {}

        result = map_successful_oicp_authorization_response_to_ocpi_221(
            oicp_response, token_id
        )
        assert result is None

    def test_mapping_with_null_response_results_in_not_allowed(self):
        token_id = "TEST123456"
        oicp_response = None

        assert (
            map_successful_oicp_authorization_response_to_ocpi_221(
                oicp_response, token_id
            )
            is None
        )

    def test_mapping_with_not_authorized_results_in_not_allowed(self):
        token_id = "TEST123456"
        oicp_response = {
            "AuthorizationStatus": "NotAuthorized",
            "ProviderID": "FI*MSP",
            "StatusCode": {"Code": "100"},  # Not a success code
            "SessionID": "HUBJECT-SESSION-1234",
        }

        result = map_successful_oicp_authorization_response_to_ocpi_221(
            oicp_response, token_id
        )
        assert result["data"]["allowed"] == "NOT_ALLOWED"
        assert result["data"]["authorization_reference"] == settings.HUBJECT_EMP_ID
        assert result["data"]["hub_session_id"] == "HUBJECT-SESSION-1234"

    def test_map_oicp_authorization_response_to_ocpi_221_success(self):
        token_id = "TEST123456"
        oicp_response = {
            "AuthorizationStatus": "Authorized",
            "ProviderID": "FI*MSP",
            "StatusCode": {"Code": "000"},
            "SessionID": "HUBJECT-SESSION-1234",
        }

        result = map_successful_oicp_authorization_response_to_ocpi_221(
            oicp_response, token_id
        )

        assert result is not None
        assert "data" in result
        data = result["data"]
        assert data["allowed"] == "ALLOWED"
        assert data["authorization_reference"] == settings.HUBJECT_EMP_ID
        assert data["hub_session_id"] == "HUBJECT-SESSION-1234"
        assert data["token"]["uid"] == token_id
        assert data["token"]["country_code"] == "FI"
        assert data["token"]["party_id"] == "MSP"
        assert data["token"]["issuer"] == "FI*MSP"

    def test_map_oicp_not_authorized_authorization_response_to_ocpi_221_results_in_not_allowed(
        self,
    ):
        token_id = "TEST123456"
        oicp_response = {
            "AuthorizationStatus": "NotAuthorized",
            "ProviderID": "FI*MSP",
            "StatusCode": {"Code": "100"},  # Not a success code
            "SessionID": "HUBJECT-SESSION-1234",
        }

        result = map_successful_oicp_authorization_response_to_ocpi_221(
            oicp_response, token_id
        )
        assert result["data"]["authorization_reference"] == settings.HUBJECT_EMP_ID
        assert result["data"]["hub_session_id"] == "HUBJECT-SESSION-1234"
        assert result["data"]["allowed"] == "NOT_ALLOWED"
        assert result["data"]["responding_party"] == settings.HUBJECT_OPERATOR_ID

    def test_map_oicp_authorization_response_to_ocpi_221_missing_status(self):
        token_id = "TEST123456"
        oicp_response = {
            "ProviderID": "FI*MSP",
            "StatusCode": {"Code": "000"},
            "SessionID": "HUBJECT-SESSION-1234",
        }

        with pytest.raises(KeyError):
            map_successful_oicp_authorization_response_to_ocpi_221(
                oicp_response, token_id
            )
