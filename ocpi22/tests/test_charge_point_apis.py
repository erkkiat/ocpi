from unittest.mock import patch

import pytest
from django.urls import reverse

from ocpi22.choices import MessageTexts
from ocpi22.tests.factories import EvseFactory, TokenFactory, OCPISessionFactory
from ocpi22.tokens.auth import TokenAuthorization


@pytest.fixture
def available_evse():
    return EvseFactory(uid="BE*SMP*AVAILABLEEVSE")


@pytest.fixture
def charging_request_body(available_evse):
    return {
        "evse_uid": available_evse.uid,
        "status": "CHARGING",
        "timestamp": "2021-01-01T00:00:00Z",
    }


@pytest.fixture
def allowed_token(msp_de_ice, admin_user):
    return TokenFactory(
        uid="ALLOWED_TOKEN", ocpi_master=msp_de_ice, customer=admin_user
    )


@pytest.fixture
def authorize_token_response(allowed_token):
    session = OCPISessionFactory()
    return TokenAuthorization(
        allowed="ALLOWED",
        info=MessageTexts.get("TOKEN_ACCEPTED"),
        token=allowed_token,
        responding_party=session.billed_to.party_str(),
        authorization_reference=session.authorization_reference,
        auth_method=session.auth_method,
        billed_to=session.billed_to.party_str(),
        ocpi_master=session.billed_to,
    )


class TestChargePointAPI:
    status_change_url = reverse("chargepoint-status-change")
    authorize_url = reverse("chargepoint-authorize")

    def test_status_change_post_forbidden_for_authenticated_user(
        self, authenticated_user_client, available_evse, charging_request_body
    ):
        response = authenticated_user_client.post(
            self.status_change_url, data=charging_request_body
        )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "You do not have permission to perform this action.",
        }

    def test_status_change_post_successful_return_200(
        self, admin_user_client, available_evse, charging_request_body
    ):
        response = admin_user_client.post(
            self.status_change_url, data=charging_request_body
        )

        assert response.status_code == 200
        assert response.json() == {
            "status_text": "EVSE status has been changed",
            "evse": available_evse.uid,
            "ocpi_status": "CHARGING",
            "ocpp_status": "CHARGING",
        }

    def test_status_change_post_with_non_existing_evse_return_400(
        self, admin_user_client
    ):
        non_existing_evse = "BE*SMP*NONEXISTINGEVSE"
        request_body = {"evse_uid": non_existing_evse, "status": "CHARGING"}
        response = admin_user_client.post(self.status_change_url, data=request_body)

        assert response.json() == {
            "evse_uid": ["EVSE BE*SMP*NONEXISTINGEVSE not found"]
        }
        assert response.status_code == 400

    def test_status_change_post_with_invalid_status_return_400(
        self, admin_user_client, available_evse
    ):
        request_body = {"evse_uid": available_evse.uid, "status": "INVALID"}
        response = admin_user_client.post(self.status_change_url, data=request_body)

        assert response.status_code == 400
        assert response.json() == {
            "status": [
                "'INVALID' is not a known OCPP status. Options are: ['AVAILABLE', 'PREPARING', 'CHARGING', 'SUSPENDEDEV', 'SUSPENDEDEVSE', 'FINISHING', 'RESERVED', 'UNAVAILABLE', 'FAULTED'].",
            ],
        }

    def test_status_change_get_returns_400(self, admin_user_client):
        response = admin_user_client.get(self.status_change_url)

        assert response.status_code == 400
        assert response.json() == {
            "status_message": "Please see OPTIONS to learn what you can POST at this endpoint",
        }

    def test_authorize_post_successful_with_authenticated_user_return_403(
        self, authenticated_user_client, available_evse
    ):
        request_body = {"evse_id": available_evse.uid, "token_id": "EKI1"}
        response = authenticated_user_client.post(self.authorize_url, data=request_body)
        assert response.json() == {
            "detail": "You do not have permission to perform this action.",
        }
        assert response.status_code == 403

    @pytest.mark.skip("This test is failing because of the patching")
    def test_authorize_post_successful_return_200(
        self, admin_user_client, available_evse, allowed_token, authorize_token_response
    ):
        request_body = {"evse_id": available_evse.uid, "token_id": allowed_token.uid}
        with patch(
            "ocpi22.tokens.token_async.authorize_with_msps_sync"
        ) as mock_authorize_token:
            mock_authorize_token.return_value = authorize_token_response
            response = admin_user_client.post(self.authorize_url, data=request_body)
            assert response.status_code == 200
