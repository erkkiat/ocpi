import pytest
from unittest.mock import MagicMock, patch, Mock

from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.tests.factories import LocationFactory, TokenFactory, CredentialsRoleFactory
from ocpi22.tokens.auth import find_authorize_party_details
from ocpi22.choices import OcpiRolesEnum, OcpiModuleEnum, EndpointRoleEnum
from ocpiconnector.party import Party
from ocpi22.routing import find_route


class TestFindAuthorizePartyDetails:
    @patch("ocpi22.tokens.auth.find_endpoints_by_roles")
    @pytest.mark.django_db
    def test_adhoc_token_triggers_find_endpoints_by_roles(self, mock_find_endpoints):
        location = LocationFactory()
        token = AdhocToken(Party(), "AdhocToken", "ADHOC", None)
        expected_result = [("url", "token", "CC", "PID", "creds")]
        mock_find_endpoints.return_value = expected_result

        result = find_authorize_party_details(Mock(), token, location.uid, adhoc=True)

        mock_find_endpoints.assert_called_once_with(
            (OcpiRolesEnum.EMSP.value, OcpiRolesEnum.HUB.value),
            OcpiModuleEnum.TOKENS,
            endpoint_role=EndpointRoleEnum.SENDER.value,
            location_uid=location.uid,
        )
        assert result == expected_result

    @pytest.mark.django_db
    def test_known_token_returns_route_successfully(self):
        request = MagicMock()
        token = TokenFactory(
            uid="KNOWN_TOKEN",
            ocpi_master=CredentialsRoleFactory(
                country_code="US", party_id="XYZ", role=OcpiRolesEnum.EMSP.value
            ),
        )
        location = LocationFactory()

        find_route.cache_clear()
        result = find_authorize_party_details(request, token, location.uid, adhoc=False)
        assert result == [
            (
                "https://localhost/ocpi/tokens",
                token.ocpi_master.credentials.theirs_base64(),
                token.ocpi_master.country_code,
                token.ocpi_master.party_id,
                token.ocpi_master.credentials,
            )
        ]

    @patch("ocpi22.tokens.auth.find_route")
    @pytest.mark.django_db
    def test_known_token_with_no_route_returns_none(self, mock_find_route, caplog):
        request = MagicMock()
        token = TokenFactory(
            uid="KNOWN_TOKEN_WITH_NO_ROUTE",
            ocpi_master=CredentialsRoleFactory(
                country_code="US", party_id="XYZ", role=OcpiRolesEnum.EMSP.value
            ),
        )
        location_uid = "loc123"
        mock_find_route.return_value = None

        result = find_authorize_party_details(request, token, location_uid, adhoc=False)
        assert (
            "Route (None) or Token (US*XYZ: RFID KNOWN_TOKEN_WITH_NO_ROUTE) missing, cannot authorize Token"
            in caplog.text
        )

        assert result is None
