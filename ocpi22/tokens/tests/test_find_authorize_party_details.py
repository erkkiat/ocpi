
import pytest
from unittest.mock import MagicMock, patch
from ocpi22.tokens.auth import find_authorize_party_details
from ocpi22.choices import OcpiRolesEnum, OcpiModuleEnum, EndpointRoleEnum

class TestFindAuthorizePartyDetails:
    
    @patch('ocpi22.tokens.auth.find_endpoints_by_roles')
    def test_adhoc_true_calls_find_endpoints_by_roles(self, mock_find_endpoints):
        # Arrange
        request = MagicMock()
        token = MagicMock()
        location_uid = "loc123"
        expected_result = [("url", "token", "CC", "PID", "creds")]
        mock_find_endpoints.return_value = expected_result

        # Act
        result = find_authorize_party_details(request, token, location_uid, adhoc=True)

        # Assert
        mock_find_endpoints.assert_called_once_with(
            (OcpiRolesEnum.EMSP.value, OcpiRolesEnum.HUB.value),
            OcpiModuleEnum.TOKENS,
            endpoint_role=EndpointRoleEnum.SENDER.value,
            location_uid=location_uid
        )
        assert result == expected_result

    @patch('ocpi22.tokens.auth.find_route')
    def test_adhoc_false_returns_route_details(self, mock_find_route):
        # Arrange
        request = MagicMock()
        token = MagicMock()
        token.get_party.return_value = "PARTY"
        location_uid = "loc123"
        
        mock_route = MagicMock()
        mock_route.url = "http://example.com"
        mock_route.token_base64 = "token_b64"
        mock_route.to.country_code = "DE"
        mock_route.to.party_id = "TEST"
        mock_route.credentials = "credentials"
        
        mock_find_route.return_value = mock_route

        expected_result = [
            (
                mock_route.url,
                mock_route.token_base64,
                mock_route.to.country_code,
                mock_route.to.party_id,
                mock_route.credentials,
            )
        ]

        # Act
        result = find_authorize_party_details(request, token, location_uid, adhoc=False)

        # Assert
        mock_find_route.assert_called_once_with(
            "PARTY", OcpiModuleEnum.TOKENS, role=EndpointRoleEnum.SENDER
        )
        assert result == expected_result

    @patch('ocpi22.tokens.auth.find_route')
    @patch('ocpi22.tokens.auth.logging')
    def test_adhoc_false_no_route_returns_none(self, mock_logging, mock_find_route):
        # Arrange
        request = MagicMock()
        token = MagicMock()
        token.get_party.return_value = "PARTY"
        location_uid = "loc123"
        mock_find_route.return_value = None

        # Act
        result = find_authorize_party_details(request, token, location_uid, adhoc=False)

        # Assert
        assert result is None
        mock_logging.warning.assert_called_once()
