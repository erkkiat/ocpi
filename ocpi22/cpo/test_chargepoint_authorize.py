import base64

import pytest

from ocpi22.cpo.api import ChargePointViewSet
from ocpi22.models.session import Session
from ocpi22.ocpi.headers import make_headers
from ocpi22.tests.factories import (
    LocationFactory,
    EvseFactory,
    TokenFactory,
    CredentialsFactory,
    CredentialsRoleFactory,
)
from ocpi22.tokens.auth import TokenAuthorization, AuthorizationEnum
from ocpiconnector.testutil import OCPIAPIRequestFactory
from util import reverse


@pytest.fixture
def evse(db):
    location = LocationFactory()
    return EvseFactory(location=location)


@pytest.fixture
def token():
    return TokenFactory(uid="SOME_TOKEN_UID")


@pytest.fixture
def ocpi_master():
    return CredentialsRoleFactory(country_code="US", party_id="TST", role="CPO")


def make_request(evse, token_data, payload=None):
    token_a = "token_a_123456"
    token_a_base64 = base64.b64encode(token_a.encode("ascii")).decode("ascii")

    credentials = CredentialsFactory(token_a=token_a, ours="", theirs="")

    api_factory = OCPIAPIRequestFactory()
    headers = make_headers(token_a_base64)
    request = api_factory.post(
        reverse("chargepoint-authorize"), data=payload, **headers
    )
    request.credentials = credentials
    request.version = "2.2.1"
    request.data = {"evse_id": evse.uid, "token_id": token_data}
    return request


def test_authorize_positive(monkeypatch, evse, token, ocpi_master):
    auth = TokenAuthorization(
        allowed=AuthorizationEnum.ALLOWED,
        token=token,
        responding_party="DE*ICE",
        authorization_reference="REF123",
        auth_method="AUTH_REQUEST",
        billed_to="FR*TST",
        ocpi_master=ocpi_master,
    )
    monkeypatch.setattr(
        "ocpi22.cpo.api.authorize_token", lambda token, location, request=None: auth
    )
    request = make_request(evse, token.uid)
    response = ChargePointViewSet().authorize(request)
    assert response.status_code == 200, response.data
    data = response.data
    assert data["allowed"] == AuthorizationEnum.ALLOWED
    assert data["token"] == token.uid
    assert data["authorization_reference"] == "REF123"
    assert data["session_id"] is not None
    session = Session.objects.filter(authorization_reference="REF123")
    assert session.count() == 1


def test_authorize_disallowed(monkeypatch, evse, token):
    auth = TokenAuthorization(
        allowed=AuthorizationEnum.NOT_ALLOWED,
        token=token,
    )
    monkeypatch.setattr(
        "ocpi22.cpo.api.authorize_token", lambda token, location, request=None: auth
    )
    request = make_request(evse, token.uid)
    request.data["evse"] = evse.uid
    response = ChargePointViewSet().authorize(request)
    assert response.status_code == 401, response.data
    data = response.data
    assert data["allowed"] == AuthorizationEnum.NOT_ALLOWED
    assert data["session_id"] is None
    assert data["token"] == token.uid
    assert not data.get("authorization_reference")


def test_authorize_missing_ocpi_master_logs_error(monkeypatch, evse, token, caplog):
    """
    If authorize_token returns allowed but ocpi_master is None, creating session should fail
    """
    auth = TokenAuthorization(
        allowed=AuthorizationEnum.ALLOWED,
        token=token,
        responding_party="DE*ICE",
        authorization_reference="REF123",
        auth_method="AUTH_REQUEST",
        billed_to="FR*TST",
        # ocpi_master left out
    )
    monkeypatch.setattr(
        "ocpi22.cpo.api.authorize_token", lambda token, location, request=None: auth
    )
    request = make_request(evse, token.uid)
    request.data["evse"] = evse.uid
    response = ChargePointViewSet().authorize(request)
    assert response.status_code == 404, response.data
    assert "Exception in CPO authorize()" in caplog.records[0].message, caplog.records[
        0
    ]
    session = Session.objects.filter(authorization_reference="REF123")
    assert session.count() == 0
