import pytest
from datetime import datetime
from django.conf import settings

from integrations.hubject.oicp_to_ocpi_converter import (
    map_oicp_authorization_response_to_ocpi_221,
)


def oicp_authorization_response(**kwargs):
    # Below is an actual response from the Hubject QA server
    response = {
        "AuthorizationStatus": "Authorized",
        "AuthorizationStopIdentifications": None,
        "CPOPartnerSessionID": None,
        "EMPPartnerSessionID": None,
        "ProviderID": "DE*ICE",
        "SessionID": "4a0fe067-de32-4ab7-9a27-0c107438a57b",
        "StatusCode": {"AdditionalInfo": None, "Code": "000", "Description": None},
    }
    response.update(kwargs)
    return response


class TestMapOICPAuthorizationResponseToOCPI221:
    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_successful_mapping_with_valid_response(self):
        """Test that a valid OICP authorization response is correctly mapped to OCPI format"""
        token_id = "TEST123456"
        oicp_response = {
            "AuthorizationStatus": "Authorized",
            "ProviderID": "FI*MSP",
            "StatusCode": {"Code": "000"},
            "SessionID": "HUBJECT-SESSION-1234",
            "EMPPartnerSessionID": "MSP-AUTHORIZATION-5678",
        }

        result = await map_oicp_authorization_response_to_ocpi_221(
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

    async def test_mapping_with_different_authorization_status_results_in_not_allowed(self):
        """Test mapping with a different authorization status than 'Authorized'"""
        token_id = "TEST123456"
        oicp_response = {
            "AuthorizationStatus": "SomeOtherStatus",  # Not "Authorized"
            "ProviderID": "FI*MSP",
            "StatusCode": {"Code": "000"},
            "SessionID": "HUBJECT-SESSION-1234",
        }

        result = await map_oicp_authorization_response_to_ocpi_221(
            oicp_response, token_id
        )

        assert result is not None
        assert result["data"]["allowed"] == "NOT_ALLOWED"
        assert result["data"]["authorization_reference"] == "HUBJECT-OMITTED"
        assert result["data"]["hub_session_id"] == "HUBJECT-SESSION-1234"

    async def test_mapping_with_complex_provider_id_succeeds(self):
        """Test mapping with a more complex ProviderID format"""
        token_id = "TEST123456"
        oicp_response = {
            "AuthorizationStatus": "Authorized",
            "ProviderID": "DE*COMPLEX123",
            "StatusCode": {"Code": "000"},
            "SessionID": "HUBJECT-SESSION-1234",
        }

        result = await map_oicp_authorization_response_to_ocpi_221(
            oicp_response, token_id
        )

        assert result is not None
        assert result["data"]["token"]["country_code"] == "DE"
        assert result["data"]["token"]["party_id"] == "COMPLEX123"
        assert result["data"]["token"]["issuer"] == "DE*COMPLEX123"

    async def test_mapping_with_failed_status_code_succeeds(self):
        """Test mapping with a non-success status code"""
        token_id = "TEST123456"
        oicp_response = {
            "AuthorizationStatus": "Authorized",
            "ProviderID": "FI*MSP",
            "StatusCode": {"Code": "100"},  # Not a success code
            "SessionID": "HUBJECT-SESSION-1234",
        }

        result = await map_oicp_authorization_response_to_ocpi_221(
            oicp_response, token_id
        )
        assert result["data"]["authorization_reference"] == "HUBJECT-OMITTED"
        assert result["data"]["hub_session_id"] == "HUBJECT-SESSION-1234"
        assert result["data"]["allowed"] == "ALLOWED"

    async def test_mapping_with_missing_authorization_status_fails(self):
        """Test mapping when AuthorizationStatus is missing"""
        token_id = "TEST123456"
        oicp_response = {
            # No AuthorizationStatus
            "ProviderID": "FI*MSP",
            "StatusCode": {"Code": "000"},
            "SessionID": "HUBJECT-SESSION-1234",
        }

        result = await map_oicp_authorization_response_to_ocpi_221(
            oicp_response, token_id
        )
        assert result is None

    async def test_mapping_with_missing_status_code_succeeds(self):
        """Test mapping when StatusCode is missing"""
        token_id = "TEST123456"
        oicp_response = {
            "AuthorizationStatus": "Authorized",
            "ProviderID": "FI*MSP",
            # No StatusCode
            "SessionID": "HUBJECT-SESSION-1234",
        }

        result = await map_oicp_authorization_response_to_ocpi_221(
            oicp_response, token_id
        )
        assert result["data"]["authorization_reference"] == "HUBJECT-OMITTED"
        assert result["data"]["hub_session_id"] == "HUBJECT-SESSION-1234"
        assert result["data"]["allowed"] == "ALLOWED"

    async def test_mapping_with_missing_provider_id_fails(self):
        """Test mapping when ProviderID is missing"""
        token_id = "TEST123456"
        oicp_response = {
            "AuthorizationStatus": "Authorized",
            # No ProviderID
            "StatusCode": {"Code": "000"},
            "SessionID": "HUBJECT-SESSION-1234",
        }

        result = map_oicp_authorization_response_to_ocpi_221(oicp_response, token_id)
        assert result is None

    async def test_mapping_with_empty_response_results_in_not_allowed(self):
        """Test mapping with an empty response"""
        token_id = "TEST123456"
        oicp_response = {}

        result = await map_oicp_authorization_response_to_ocpi_221(
            oicp_response, token_id
        )
        assert result is None

    async def test_mapping_with_null_response_results_in_not_allowed(self):
        """Test mapping with a None response"""
        token_id = "TEST123456"
        oicp_response = None

        assert (
            await map_oicp_authorization_response_to_ocpi_221(oicp_response, token_id)
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

        result = map_oicp_authorization_response_to_ocpi_221(oicp_response, token_id)
        assert result["data"]["allowed"] == "NOT_ALLOWED"
        assert result["data"]["authorization_reference"] == "HUBJECT-OMITTED"
        assert result["data"]["hub_session_id"] == "HUBJECT-SESSION-1234"
