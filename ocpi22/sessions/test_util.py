import pytest

from ocpi22.models.cdrtoken import CdrToken
from ocpi22.models.session import Session
from ocpi22.tests.factories import (
    LocationFactory,
    EvseFactory,
    TokenFactory,
    CredentialsRoleFactory,
)
from ocpi22.tokens.auth import TokenAuthorization, AuthorizationEnum
from util import reverse


@pytest.fixture
def emsp_credentials_role(db):
    return CredentialsRoleFactory(country_code="NL", party_id="EMS", role="EMSP")


@pytest.fixture
def hub_credentials_role(db):
    return CredentialsRoleFactory(
        country_code="FR",
        party_id="HUB",
        role="HUB",
        business_details__name="HubOperator",
    )


@pytest.fixture
def cpo_credentials_role(db):
    return CredentialsRoleFactory(country_code="FI", party_id="CPO", role="CPO")


@pytest.fixture
def location(cpo_credentials_role):
    return LocationFactory(ocpi_master=cpo_credentials_role, uid="LOC123")


@pytest.fixture
def evse(location):
    return EvseFactory(location=location, uid="EVSE123")


@pytest.fixture
def token(emsp_credentials_role):
    return TokenFactory(
        uid="TOKEN123", ocpi_master=emsp_credentials_role, contract_id="CONTRACT123"
    )


@pytest.mark.django_db
class TestCreateSession:
    def test_authorize_sets_cdr_token_ocpi_master_to_token_ocpi_master(
        self,
        monkeypatch,
        admin_user_client,
        evse,
        token,
        emsp_credentials_role,
        hub_credentials_role,
        cpo_credentials_role,
    ):
        auth = TokenAuthorization(
            allowed=AuthorizationEnum.ALLOWED,
            token=token,
            responding_party=f"{hub_credentials_role.country_code}*{hub_credentials_role.party_id}",
            authorization_reference="REF123",
            auth_method="AUTH_REQUEST",
            billed_to=f"{emsp_credentials_role.country_code}*{emsp_credentials_role.party_id}",
            ocpi_master=emsp_credentials_role,
        )
        monkeypatch.setattr(
            "ocpi22.cpo.api.authorize_token", lambda token, location, request=None: auth
        )
        monkeypatch.setattr(
            "ocpi22.sessions.util.generate_session_uid", lambda: "SESSION_ID_123"
        )

        response = admin_user_client.post(
            reverse("chargepoint-authorize"),
            data={"evse_id": evse.uid, "token_id": token.uid},
            format="json",
        )

        assert response.status_code == 200, response.data

        session = Session.objects.get(uid="SESSION_ID_123")
        assert session.billed_to == emsp_credentials_role
        assert session.ocpi_master == cpo_credentials_role
        assert session.credentials == hub_credentials_role.credentials

        # The bug: cdr_token.ocpi_master is set to billed_to instead of token.ocpi_master
        # This test should fail with the current implementation
        cdr_token = CdrToken.objects.get(
            uid=token.uid, token_type=token.type, contract_id=token.contract_id
        )
        # cdr_token.ocpi_master should always be the token issuer (EMSP), not billed_to
        assert cdr_token.ocpi_master == token.ocpi_master
        assert cdr_token.ocpi_master == emsp_credentials_role
