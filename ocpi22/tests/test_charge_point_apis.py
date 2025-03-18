import pytest
from django.urls import reverse

from ocpi22.tests.factories import EvseFactory, TokenFactory


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


def allowed_token():
    return TokenFactory(token_id="ALLOWED_TOKEN")


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
        self, admin_client, available_evse, charging_request_body
    ):
        response = admin_client.post(self.status_change_url, data=charging_request_body)

        assert response.status_code == 200
        assert response.json() == {
            "status_text": "EVSE status has been changed",
            "evse": available_evse.uid,
            "ocpi_status": "CHARGING",
            "ocpp_status": "CHARGING",
        }

    def test_status_change_post_with_non_existing_evse_return_400(self, admin_client):
        non_existing_evse = "BE*SMP*NONEXISTINGEVSE"
        request_body = {"evse_uid": non_existing_evse, "status": "CHARGING"}
        response = admin_client.post(self.status_change_url, data=request_body)

        assert response.json() == {
            "evse_uid": ["EVSE BE*SMP*NONEXISTINGEVSE not found"]
        }
        assert response.status_code == 400

    def test_status_change_post_with_invalid_status_return_400(
        self, admin_client, available_evse
    ):
        request_body = {"evse_uid": available_evse.uid, "status": "INVALID"}
        response = admin_client.post(self.status_change_url, data=request_body)

        assert response.status_code == 400
        assert response.json() == {
            "status": [
                "'INVALID' is not a known OCPP status. Options are: ['AVAILABLE', 'PREPARING', 'CHARGING', 'SUSPENDEDEV', 'SUSPENDEDEVSE', 'FINISHING', 'RESERVED', 'UNAVAILABLE', 'FAULTED'].",
            ],
        }

    def test_status_change_get_returns_400(self, admin_client):
        response = admin_client.get(self.status_change_url)

        assert response.status_code == 400
        assert response.json() == {
            "status_message": "Please see OPTIONS to learn what you can POST at this endpoint",
        }
