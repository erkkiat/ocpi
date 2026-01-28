from unittest.mock import patch

import pytest
import time_machine
from django.urls import reverse

from ocpi22.choices import MessageTexts, AuthorizationEnum
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.routing import find_route
from ocpi22.tests.factories import (
    EvseFactory,
    TokenFactory,
    OCPISessionFactory,
    ConnectorFactory,
    LocationFactory,
    CredentialsRoleFactory,
    TariffFactory,
)
from ocpi22.tokens.auth import TokenAuthorization, _authorize_token
from ocpi22.tokens.dataclasses import TokenDto


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


@pytest.fixture(autouse=True)
def clear_authorize_token_cache():
    get_credentialsrole.cache_clear()
    _authorize_token.cache_clear()
    find_route.cache_clear()


@pytest.fixture
def session():
    location = LocationFactory(uid="08C70E1E-BE47-44FC-BF84-1B56ADD17B4F")
    evse = EvseFactory(uid="1743399882", location=location)
    connector = ConnectorFactory(id=1, uid="1", evse=evse)

    return OCPISessionFactory(
        uid="SESSION_ID_1234",
        start_kwh=0,
        connector=connector,
        location=location,
        evse=evse,
        billed_to=CredentialsRoleFactory(
            country_code="FI", party_id="MSP", role="EMSP"
        ),
        credentials=CredentialsRoleFactory(
            country_code="FR",
            party_id="207",
            role="HUB",
            business_details__name="Gireve",
        ).credentials,
    )


@pytest.fixture
def allowed_token(msp_de_icd, admin_user):
    return TokenFactory(
        uid="ALLOWED_TOKEN", ocpi_master=msp_de_icd, customer=admin_user
    )


@pytest.fixture
def always_token(msp_de_ice, admin_user):
    return TokenFactory(
        uid="ALWAYS_TOKEN",
        ocpi_master=msp_de_ice,
        customer=admin_user,
        whitelist="ALWAYS",
    )


@pytest.fixture
def never_token(msp_de_icd, admin_user):
    return TokenFactory(
        uid="NEVER_TOKEN",
        ocpi_master=msp_de_icd,
        customer=admin_user,
        whitelist="NEVER",
    )


@pytest.fixture
def allowed_offline_token(msp_de_icd, admin_user):
    return TokenFactory(
        uid="ALLOWED_OFFLINE_TOKEN",
        ocpi_master=msp_de_icd,
        customer=admin_user,
        whitelist="ALLOWED_OFFLINE",
    )


@pytest.fixture
def authorize_token_response(allowed_token, session):
    return TokenAuthorization(
        allowed="ALLOWED",
        info=MessageTexts.get("TOKEN_ACCEPTED"),
        token=allowed_token,
        responding_party=session.billed_to.party_str(),
        authorization_reference=session.authorization_reference,
        auth_method=session.auth_method,
        billed_to=session.billed_to.party_str(),
        msp=session.billed_to,
    )


@pytest.fixture
def authorize_whitelist_token_response(always_token, session):
    return TokenAuthorization(
        allowed="ALLOWED",
        info=MessageTexts.get("TOKEN_ACCEPTED"),
        token=always_token,
        responding_party=session.billed_to.party_str(),
        authorization_reference=session.authorization_reference,
        auth_method=session.auth_method,
        billed_to=session.billed_to.party_str(),
        msp=session.billed_to,
    )


@pytest.fixture
def authorize_never_token_success_response(never_token, session):
    return TokenAuthorization(
        allowed="ALLOWED",
        info=MessageTexts.get("TOKEN_ACCEPTED"),
        token=never_token,
        responding_party=session.billed_to.party_str(),
        authorization_reference=session.authorization_reference,
        auth_method=session.auth_method,
        billed_to=session.billed_to.party_str(),
        msp=session.billed_to,
    )


@pytest.fixture
def authorize_never_token_not_allowed_response(never_token, session):
    return TokenAuthorization(
        allowed="NOT_ALLOWED",
        info=MessageTexts.get("TOKEN_ACCEPTED"),
        token=never_token,
        responding_party=session.billed_to.party_str(),
        authorization_reference=session.authorization_reference,
        auth_method=session.auth_method,
        billed_to=session.billed_to.party_str(),
        msp=session.billed_to,
    )


class TestChargePointAPI:
    status_change_url = reverse("chargepoint-status-change")
    authorize_url = reverse("chargepoint-authorize")
    start_transaction_url = reverse("chargepoint-start-transaction")
    meter_values_url = reverse("chargepoint-meter-values")
    stop_transaction_url = reverse("chargepoint-stop-transaction")

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

    def test_authorize_post_successful_return_200(
        self, admin_user_client, available_evse, allowed_token, authorize_token_response
    ):
        request_body = {"evse_id": available_evse.uid, "token_id": allowed_token.uid}
        with patch(
            "ocpi22.tokens.auth.authorize_with_msps_sync"
        ) as mock_authorize_token:
            mock_authorize_token.return_value = authorize_token_response
            response = admin_user_client.post(self.authorize_url, data=request_body)
            assert response.status_code == 200
            mock_authorize_token.assert_called_once_with(
                TokenDto(uid=allowed_token.uid, adhoc=False, token=allowed_token),
                [
                    (
                        "https://localhost/ocpi/tokens",
                        allowed_token.ocpi_master.credentials.theirs_base64(),
                        allowed_token.ocpi_master.country_code,
                        allowed_token.ocpi_master.party_id,
                        allowed_token.ocpi_master.credentials,
                    )
                ],
                available_evse.location
            )
            assert response.data["allowed"] == AuthorizationEnum.ALLOWED
            assert response.data["token"] == authorize_token_response.token.uid

    @pytest.mark.skip(
        "We don't know how to route session updates for whitelisted tokens, so this will not work"
    )
    def test_authorize_with_whitelisted_token_successful_return_200(
        self,
        admin_user_client,
        available_evse,
        always_token,
        authorize_whitelist_token_response,
    ):
        request_body = {"evse_id": available_evse.uid, "token_id": always_token.uid}
        with patch(
            "ocpi22.tokens.auth.authorize_with_msps_sync"
        ) as mock_authorize_token:
            mock_authorize_token.return_value = authorize_whitelist_token_response
            response = admin_user_client.post(self.authorize_url, data=request_body)
            assert response.status_code == 200
            assert mock_authorize_token.call_count == 0
            assert response.data["allowed"] == AuthorizationEnum.ALLOWED
            assert (
                response.data["token"] == authorize_whitelist_token_response.token.uid
            )

    def test_authorize_with_never_token_successful_return_200(
        self,
        admin_user_client,
        available_evse,
        never_token,
        authorize_never_token_success_response,
    ):
        get_credentialsrole.cache_clear()
        request_body = {"evse_id": available_evse.uid, "token_id": never_token.uid}
        with patch(
            "ocpi22.tokens.auth.authorize_with_msps_sync"
        ) as mock_authorize_token:
            mock_authorize_token.return_value = authorize_never_token_success_response
            response = admin_user_client.post(self.authorize_url, data=request_body)
            assert response.status_code == 200
            mock_authorize_token.assert_called_once_with(
                TokenDto(uid=never_token.uid, adhoc=False, token=never_token),
                [
                    (
                        "https://localhost/ocpi/tokens",
                        never_token.ocpi_master.credentials.theirs_base64(),
                        never_token.ocpi_master.country_code,
                        never_token.ocpi_master.party_id,
                        never_token.ocpi_master.credentials,
                    )
                ],
                available_evse.location
            )
            assert response.data["allowed"] == AuthorizationEnum.ALLOWED
            assert (
                response.data["token"]
                == authorize_never_token_success_response.token.uid
            )

    def test_authorize_with_never_token_unauthorized(
        self,
        admin_user_client,
        available_evse,
        never_token,
        authorize_never_token_not_allowed_response,
    ):
        request_body = {"evse_id": available_evse.uid, "token_id": never_token.uid}
        with patch(
            "ocpi22.tokens.auth.authorize_with_msps_sync"
        ) as mock_authorize_token:
            mock_authorize_token.return_value = (
                authorize_never_token_not_allowed_response
            )
            response = admin_user_client.post(self.authorize_url, data=request_body)
            assert response.status_code == 401
            mock_authorize_token.assert_called_once_with(
                TokenDto(uid=never_token.uid, adhoc=False, token=never_token),
                [
                    (
                        "https://localhost/ocpi/tokens",
                        never_token.ocpi_master.credentials.theirs_base64(),
                        never_token.ocpi_master.country_code,
                        never_token.ocpi_master.party_id,
                        never_token.ocpi_master.credentials,
                    )
                ],
                available_evse.location
            )
            assert response.data["allowed"] == AuthorizationEnum.NOT_ALLOWED
            assert (
                response.data["token"]
                == authorize_never_token_not_allowed_response.token.uid
            )

    def test_start_transaction_post_successful_return_200(
        self, admin_user_client, session
    ):
        request_body = {
            "session_id": session.uid,
            "connector_id": session.connector_id,
            "start_kwh": 0,
        }
        with patch("ocpi22.cpo.api.authorize_token") as mock_authorize_token:
            mock_authorize_token.return_value = TokenAuthorization(
                allowed="ALLOWED",
                token=session.cdr_token,
                responding_party=session.billed_to.party_str(),
                authorization_reference=session.authorization_reference,
                auth_method=session.auth_method,
                billed_to=session.billed_to.party_str(),
                msp=session.billed_to,
            )
            response = admin_user_client.post(
                self.start_transaction_url, data=request_body
            )
        assert response.status_code == 200
        assert response.json() == {
            "session_id": "SESSION_ID_1234",
            "billed_to": "FI*MSP",
            "start_date_time": "2021-01-01T10:00:00Z",
            "end_date_time": "2021-01-01T12:00:00Z",
            "start_kwh": 0.0,
            "stop_kwh": 0.0,
            "token": {
                "country_code": "FI",
                "party_id": "MSP",
                "token_id": "DEADC0DE",
                "type": "RFID",
                "contract_id": "CONTRACT-12345",
            },
            "auth_method": "AUTH_REQUEST",
            "authorization_reference": "AUTHORIZATION-12345",
            "location_id": "08C70E1E-BE47-44FC-BF84-1B56ADD17B4F",
            "evse_uid": "1743399882",
            "connector_id": "1",
            "currency": "EUR",
            "total_cost_incl_vat": 12.0,
            "total_cost_excl_vat": 10.0,
            "total_kwh": 0.0,
            "status": "ACTIVE",
            "last_updated": "2021-01-01T12:00:00Z",
        }

    @time_machine.travel("2025-03-31 06:26:58")
    def test_stop_transaction_post_with_unauthenticated_client_return_401(self, client):
        request_body = {"session_id": "Session123", "stop_kwh": 10}
        response = client.post(self.stop_transaction_url, data=request_body)
        assert response.status_code == 401

    @time_machine.travel("2025-03-31 06:26:58")
    def test_stop_transaction_post_with_not_an_admin_client_return_403(
        self, authenticated_user_client
    ):
        request_body = {"session_id": "Session123", "stop_kwh": 10}
        response = authenticated_user_client.post(
            self.stop_transaction_url, data=request_body
        )
        assert response.status_code == 403

    @time_machine.travel("2025-03-31 06:26:58")
    def test_stop_transaction_post_return_200(
        self, admin_user_client, session, authorize_token_response
    ):
        with patch(
            "ocpi22.tokens.auth.authorize_with_msps_sync"
        ) as mock_authorize_token:
            mock_authorize_token.return_value = authorize_token_response
            request_body = {"session_id": session.uid, "stop_kwh": 10}
            response = admin_user_client.post(
                self.stop_transaction_url, data=request_body
            )
            assert response.status_code == 200
            assert response.json() == {
                "auth_method": "AUTH_REQUEST",
                "authorization_reference": "AUTHORIZATION-12345",
                "billed_to": "FI*MSP",
                "connector_id": "1",
                "currency": "EUR",
                "end_date_time": "2025-03-31T06:26:58Z",
                "evse_uid": "1743399882",
                "last_updated": "2025-03-31T06:26:58Z",
                "location_id": "08C70E1E-BE47-44FC-BF84-1B56ADD17B4F",
                "session_id": "SESSION_ID_1234",
                "start_date_time": "2021-01-01T10:00:00Z",
                "start_kwh": 0.0,
                "status": "COMPLETED",
                "stop_kwh": 10.0,
                "token": {
                    "contract_id": "CONTRACT-12345",
                    "country_code": "FI",
                    "party_id": "MSP",
                    "token_id": "DEADC0DE",
                    "type": "RFID",
                },
                "total_cost_excl_vat": 0.8,
                "total_cost_incl_vat": 0.9,
                "total_kwh": 10.0,
            }

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "stop_kwh, expected_status_code",
        [
            (0, 200),
            (-1, 400),
            (10000.1234, 200),
            ("invalid", 400),
        ],
    )
    def test_stop_transaction_post_with_stop_kwh_returns_expected_response(
        self, admin_user_client, session, stop_kwh, expected_status_code
    ):
        request_body = {
            "session_id": session.uid,
            "stop_kwh": stop_kwh,
        }
        response = admin_user_client.post(self.stop_transaction_url, data=request_body)
        assert response.status_code == expected_status_code

    @pytest.mark.django_db
    def test_stop_transaction_post_with_invalid_stop_kwh_returns_400(
        self, admin_user_client, session
    ):
        request_body = {
            "session_id": session.uid,
            "stop_kwh": "invalid",
        }
        response = admin_user_client.post(self.stop_transaction_url, data=request_body)
        assert response.status_code == 400
        assert response.json() == {
            "stop_kwh": [
                "A valid number is required.",
            ],
        }

    @pytest.mark.django_db
    def test_stop_transaction_post_require_stop_kwh_returns_400(
        self, admin_user_client, session
    ):
        request_body = {
            "session_id": session.uid,
        }
        response = admin_user_client.post(self.stop_transaction_url, data=request_body)
        assert response.status_code == 400
        assert response.json() == {
            "stop_kwh": ["This field is required."],
        }

    @pytest.mark.django_db
    def test_stop_transaction_post_with_timestamp_returns_200(
        self, admin_user_client, session
    ):
        request_body = {
            "session_id": session.uid,
            "stop_kwh": 100,
            "timestamp": "2025-03-31T06:26:58Z",
        }
        response = admin_user_client.post(self.stop_transaction_url, data=request_body)
        assert response.status_code == 200
        assert response.json()["end_date_time"] == "2025-03-31T06:26:58Z"

    @pytest.mark.django_db
    def test_stop_transaction_post_with_duplicate_tariffs_returns_200(
        self, admin_user_client, session, caplog
    ):
        TariffFactory(uid="CP1")
        tariff = TariffFactory(uid="CP1")
        session.connector.tariff_ids.set([tariff])
        session.save()

        request_body = {
            "session_id": session.uid,
            "stop_kwh": 100,
            "timestamp": "2025-03-31T06:26:58Z",
        }
        response = admin_user_client.post(self.stop_transaction_url, data=request_body)
        assert response.status_code == 200
        assert (
            "There are more than one Tariff with the criteria {'uid': 'CP1', 'archived': False} in the database"
            in caplog.text
        )

    @pytest.mark.django_db
    def test_stop_transaction_post_with_no_tariffs_returns_200(
        self, admin_user_client, session, caplog
    ):
        request_body = {
            "session_id": session.uid,
            "stop_kwh": 100,
            "timestamp": "2025-03-31T06:26:58Z",
        }
        response = admin_user_client.post(self.stop_transaction_url, data=request_body)
        assert response.status_code == 200

    def test_stop_transaction_post_with_nonexistent_session_returns_404(
        self, admin_user_client
    ):
        request_body = {"session_id": "NONEXISTENT_SESSION", "stop_kwh": 10}
        response = admin_user_client.post(self.stop_transaction_url, data=request_body)
        assert response.status_code == 404

    def test_stop_transaction_post_with_completed_session_returns_409(
        self, admin_user_client, session
    ):
        session.status = "COMPLETED"
        session.save()
        request_body = {"session_id": session.uid, "stop_kwh": 100}
        response = admin_user_client.post(self.stop_transaction_url, data=request_body)
        assert response.status_code == 409
        assert response.json() == {
            "status_text": "Session was completed earlier, cannot stop it twice"
        }

    @patch("ocpi22.cpo.session_service.SessionService.stop_and_create_cdr")
    def test_stop_transaction_post_calls_stop_and_create_cdr(
        self, mock_stop_and_create_cdr, admin_user_client, session
    ):
        request_body = {
            "session_id": session.uid,
            "stop_kwh": 50,
        }
        admin_user_client.post(self.stop_transaction_url, data=request_body)
        mock_stop_and_create_cdr.assert_called_once()
        call_kwargs = mock_stop_and_create_cdr.call_args[1]
        assert call_kwargs["session"] == session
        assert call_kwargs["stop_kwh"] == 50

    @patch("ocpi22.models.session.Session.send_updates")
    def test_stop_transaction_post_sends_updates_with_end_notification(
        self, mock_send_updates, admin_user_client, session
    ):
        tariff = TariffFactory(uid="TARIFF_001")
        session.connector.tariff_ids.add(tariff)
        request_body = {"session_id": session.uid, "stop_kwh": 50}
        admin_user_client.post(self.stop_transaction_url, data=request_body)
        mock_send_updates.assert_called_once()

    def test_stop_transaction_post_creates_cdr(self, admin_user_client, session):
        from ocpi22.models.cdr import Cdr

        tariff = TariffFactory(uid="TARIFF_001")
        session.connector.tariff_ids.add(tariff)
        request_body = {"session_id": session.uid, "stop_kwh": 100}
        response = admin_user_client.post(self.stop_transaction_url, data=request_body)
        assert response.status_code == 200
        cdr = Cdr.objects.filter(session_id=session.uid).first()
        assert cdr is not None

    def test_stop_transaction_post_calculates_total_kwh_correctly(
        self, admin_user_client, session
    ):
        tariff = TariffFactory(uid="TARIFF_001")
        session.connector.tariff_ids.add(tariff)
        session.start_kwh = 10
        session.save()
        request_body = {"session_id": session.uid, "stop_kwh": 110}
        response = admin_user_client.post(self.stop_transaction_url, data=request_body)
        assert response.status_code == 200
        assert response.json()["total_kwh"] == 100.0

    @time_machine.travel("2025-03-31 06:26:58")
    def test_stop_transaction_post_updates_session_status_to_completed(
        self, admin_user_client, session
    ):
        tariff = TariffFactory(uid="TARIFF_001")
        session.connector.tariff_ids.add(tariff)
        request_body = {"session_id": session.uid, "stop_kwh": 50}
        response = admin_user_client.post(self.stop_transaction_url, data=request_body)
        assert response.status_code == 200
        session.refresh_from_db()
        assert session.status == "COMPLETED"

    def test_stop_transaction_get_returns_400(self, admin_user_client):
        response = admin_user_client.get(self.stop_transaction_url)
        assert response.status_code == 400
        assert response.json() == {
            "status_message": "Please see OPTIONS to learn what you can POST at this endpoint",
        }
