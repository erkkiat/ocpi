import pytest
from unittest.mock import MagicMock, patch

from ocpi22.tests.factories import LocationFactory, TokenFactory, CredentialsRoleFactory
from ocpi22.tokens.auth import find_authorize_party_details
from ocpi22.choices import OcpiRolesEnum
from ocpi22.tokens.dataclasses import TokenDto
from ocpi22.routing import find_route


class TestFindAuthorizePartyDetails:
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
        token_dto = TokenDto(uid=token.uid, adhoc=False, token=token)
        result = find_authorize_party_details(request, token_dto, location.uid)
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

        result = find_authorize_party_details(request, TokenDto(uid=token.uid, adhoc=False, token=token), location_uid)
        assert (
            "Route (None) or Token (US*XYZ: RFID KNOWN_TOKEN_WITH_NO_ROUTE) missing, cannot authorize Token"
            in caplog.text
        )

        assert result is None
