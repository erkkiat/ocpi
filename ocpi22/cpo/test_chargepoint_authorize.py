import pytest

from ocpi22.models.session import Session
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.tests.factories import (
    LocationFactory,
    EvseFactory,
    TokenFactory,
    CredentialsRoleFactoryWithoutCredentials,
    CredentialsRoleFactory,
)
from ocpi22.tokens.auth import TokenAuthorization, AuthorizationEnum
from util import reverse


@pytest.fixture
def evse(db):
    location = LocationFactory()
    return EvseFactory(location=location)


@pytest.fixture
def ocpi_master():
    return CredentialsRoleFactoryWithoutCredentials(
        country_code="US", party_id="TST", role="EMSP"
    )


@pytest.fixture
def gireve_credentials():
    return CredentialsRoleFactory(
        country_code="FR", party_id="107", role="HUB", business_details__name="Gireve"
    ).credentials


@pytest.fixture
def token(ocpi_master):
    return TokenFactory(uid="SOME_TOKEN_UID", ocpi_master=ocpi_master)


def test_authorize_successful_with_200(
    monkeypatch, evse, token, ocpi_master, gireve_credentials, admin_user_client
):
    auth = TokenAuthorization(
        allowed=AuthorizationEnum.ALLOWED,
        token=token,
        responding_party="FR*107",
        authorization_reference="REF123",
        auth_method="AUTH_REQUEST",
        billed_to="US*TST",
        msp=ocpi_master,
    )
    monkeypatch.setattr(
        "ocpi22.cpo.api.authorize_token",
        lambda token, location, evse_id=evse.evse_id, request=None: auth,
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
    data = response.data
    assert data["allowed"] == AuthorizationEnum.ALLOWED
    assert data["token"] == token.uid
    assert data["authorization_reference"] == "REF123"
    assert data["session_id"] == "SESSION_ID_123", data["session_id"]
    session = Session.objects.get(authorization_reference="REF123")
    assert session.credentials == gireve_credentials
    assert session.ocpi_master == evse.location.ocpi_master


def test_authorize_with_non_existent_credentialsrole_fails_with_404(
    monkeypatch, evse, token, ocpi_master, caplog, admin_user_client
):
    get_credentialsrole.cache_clear()
    auth = TokenAuthorization(
        allowed=AuthorizationEnum.ALLOWED,
        token=token,
        responding_party="DE*ICE",
        authorization_reference="REF123",
        auth_method="AUTH_REQUEST",
        billed_to="FR*TST",
        msp=ocpi_master,
    )
    monkeypatch.setattr(
        "ocpi22.cpo.api.authorize_token",
        lambda token, location, evse_id=evse.evse_id, request=None: auth,
    )
    response = admin_user_client.post(
        reverse("chargepoint-authorize"),
        data={"evse_id": evse.uid, "token_id": token.uid},
        format="json",
    )
    assert response.status_code == 404, response.data
    assert "DE*ICE not found" in response.data["status_message"], response.data
    assert "Exception in CPO authorize()" in caplog.text, caplog.text


def test_authorize_disallowed(monkeypatch, evse, token, admin_user_client):
    auth = TokenAuthorization(
        allowed=AuthorizationEnum.NOT_ALLOWED, token=token, responding_party="FR*107"
    )
    monkeypatch.setattr(
        "ocpi22.cpo.api.authorize_token",
        lambda token, location, evse_id=evse.evse_id, request=None: auth,
    )
    response = admin_user_client.post(
        reverse("chargepoint-authorize"),
        data={"evse_id": evse.uid, "token_id": token.uid},
        format="json",
    )
    assert response.status_code == 401, response.data
    data = response.data
    assert data["allowed"] == AuthorizationEnum.NOT_ALLOWED
    assert data["session_id"] is None
    assert data["token"] == token.uid
    assert not data.get("authorization_reference")


def test_authorize_requires_privileges_returns_403(
    monkeypatch, evse, token, authenticated_user_client
):
    response = authenticated_user_client.post(
        reverse("chargepoint-authorize"),
        data={"evse_id": evse.uid, "token_id": token.uid},
        format="json",
    )
    assert response.status_code == 403, response.data
