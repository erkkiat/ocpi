import pytest
from unittest.mock import patch
from datetime import datetime

import pytz
import time_machine
from django.urls import reverse

from ocpi22.commands.serializers import CommandResultType
from ocpi22.models.enum import AuthMethodChoices
from ocpi22.models.session import Session
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.tests.factories import (
    OCPISessionFactory,
    ConnectorFactory,
    LocationFactory,
    EvseFactory,
    CredentialsRoleFactory,
    TariffFactory,
)


@pytest.fixture
def remote_command_session():
    location = LocationFactory(uid="LOC-REMOTE-CMD")
    evse = EvseFactory(uid="EVSE-REMOTE-CMD", location=location)
    connector = ConnectorFactory(id=1, uid="CONN-1", evse=evse)
    tariff = TariffFactory(uid="TARIFF-REMOTE")
    connector.tariff_ids.set([tariff])

    return OCPISessionFactory(
        uid="REMOTE-CMD-SESSION-001",
        start_kwh=0,
        stop_kwh=0,
        connector=connector,
        location=location,
        evse=evse,
        auth_method=AuthMethodChoices.COMMAND,
        status=Session.PENDING,
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
def hubject_credentialsrole():
    return CredentialsRoleFactory(
        country_code="DE",
        party_id="ICE",
        role="HUB",
    )


@pytest.mark.django_db
class TestStartTransactionRemoteCommand:
    start_transaction_url = reverse("chargepoint-start-transaction")

    def test_start_transaction_with_command_auth_method_sends_callback_and_returns_200(
        self, admin_user_client, remote_command_session, hubject_credentialsrole
    ):
        get_credentialsrole.cache_clear()
        request_body = {
            "session_id": remote_command_session.uid,
            "connector_id": remote_command_session.connector_id,
            "start_kwh": 10.5,
        }

        with (
            patch(
                "ocpi22.cpo.session_service.send_callback.delay"
            ) as mock_send_callback,
            patch.object(Session, "send_updates"),
        ):
            response = admin_user_client.post(
                self.start_transaction_url, data=request_body
            )

            assert response.status_code == 200
            mock_send_callback.assert_called_once_with(
                session_uid=remote_command_session.uid,
                result=CommandResultType.ACCEPTED.value,
            )

    def test_start_transaction_with_command_auth_method_sets_session_to_active(
        self, admin_user_client, remote_command_session
    ):
        request_body = {
            "session_id": remote_command_session.uid,
            "connector_id": remote_command_session.connector_id,
            "start_kwh": 15.0,
        }

        with (
            patch("ocpi22.cpo.session_service.send_callback.delay"),
            patch.object(Session, "send_updates"),
        ):
            response = admin_user_client.post(
                self.start_transaction_url, data=request_body
            )

            assert response.status_code == 200
            remote_command_session.refresh_from_db()
            assert remote_command_session.status == Session.ACTIVE

    def test_start_transaction_with_command_auth_method_sets_start_kwh(
        self, admin_user_client, remote_command_session
    ):
        expected_start_kwh = 25.75
        request_body = {
            "session_id": remote_command_session.uid,
            "connector_id": remote_command_session.connector_id,
            "start_kwh": expected_start_kwh,
        }

        with (
            patch("ocpi22.cpo.session_service.send_callback.delay"),
            patch.object(Session, "send_updates"),
        ):
            response = admin_user_client.post(
                self.start_transaction_url, data=request_body
            )

            assert response.status_code == 200
            remote_command_session.refresh_from_db()
            assert remote_command_session.start_kwh == expected_start_kwh

    def test_start_transaction_with_command_auth_method_sends_updates(
        self, admin_user_client, remote_command_session
    ):
        request_body = {
            "session_id": remote_command_session.uid,
            "connector_id": remote_command_session.connector_id,
            "start_kwh": 0,
        }

        with (
            patch("ocpi22.cpo.session_service.send_callback.delay"),
            patch.object(Session, "send_updates") as mock_send_updates,
        ):
            response = admin_user_client.post(
                self.start_transaction_url, data=request_body
            )

            assert response.status_code == 200
            mock_send_updates.assert_called_once()

    def test_start_transaction_with_command_auth_method_returns_session_data(
        self, admin_user_client, remote_command_session
    ):
        request_body = {
            "session_id": remote_command_session.uid,
            "connector_id": remote_command_session.connector_id,
            "start_kwh": 5.0,
        }

        with (
            patch("ocpi22.cpo.session_service.send_callback.delay"),
            patch.object(Session, "send_updates"),
        ):
            response = admin_user_client.post(
                self.start_transaction_url, data=request_body
            )

            assert response.status_code == 200
            response_data = response.json()

            remote_command_session.refresh_from_db()

            assert response_data["session_id"] == remote_command_session.uid
            assert response_data["billed_to"] == "FI*MSP"
            assert response_data["start_kwh"] == 5.0
            assert response_data["status"] == Session.ACTIVE
            assert response_data["auth_method"] == AuthMethodChoices.COMMAND
            assert response_data["authorization_reference"] == "AUTHORIZATION-12345"
            assert response_data["location_id"] == "LOC-REMOTE-CMD"
            assert response_data["evse_uid"] == "EVSE-REMOTE-CMD"
            assert response_data["connector_id"] == "CONN-1"
            assert response_data["currency"] == remote_command_session.currency
            assert response_data["total_kwh"] == 0.0
            assert "start_date_time" in response_data
            assert "last_updated" in response_data
            assert "token" in response_data
            assert (
                response_data["token"]["token_id"]
                == remote_command_session.cdr_token.uid
            )
            assert (
                response_data["token"]["country_code"]
                == remote_command_session.cdr_token.ocpi_master.country_code
            )
            assert (
                response_data["token"]["party_id"]
                == remote_command_session.cdr_token.ocpi_master.party_id
            )

            assert remote_command_session.status == Session.ACTIVE
            assert remote_command_session.start_kwh == 5.0
            assert remote_command_session.stop_kwh == 5.0

    def test_start_transaction_with_command_auth_method_does_not_authorize_token(
        self, admin_user_client, remote_command_session
    ):
        request_body = {
            "session_id": remote_command_session.uid,
            "connector_id": remote_command_session.connector_id,
            "start_kwh": 0,
        }

        with (
            patch("ocpi22.cpo.session_service.send_callback.delay"),
            patch("ocpi22.cpo.api.authorize_token") as mock_authorize,
        ):
            response = admin_user_client.post(
                self.start_transaction_url, data=request_body
            )

            assert response.status_code == 200
            mock_authorize.assert_not_called()

    @pytest.mark.parametrize(
        "start_kwh",
        [0.0, 10.5, 100.0, 1234.56],
    )
    def test_start_transaction_with_command_auth_method_handles_various_start_kwh_values(
        self, admin_user_client, remote_command_session, start_kwh
    ):
        request_body = {
            "session_id": remote_command_session.uid,
            "connector_id": remote_command_session.connector_id,
            "start_kwh": start_kwh,
        }

        with (
            patch("ocpi22.cpo.session_service.send_callback.delay"),
            patch.object(Session, "send_updates"),
        ):
            response = admin_user_client.post(
                self.start_transaction_url, data=request_body
            )

            assert response.status_code == 200
            remote_command_session.refresh_from_db()
            assert remote_command_session.start_kwh == start_kwh

    def test_start_transaction_with_missing_session_id_returns_400(
        self, admin_user_client, remote_command_session
    ):
        request_body = {
            "connector_id": remote_command_session.connector_id,
            "start_kwh": 0,
        }

        response = admin_user_client.post(self.start_transaction_url, data=request_body)

        assert response.status_code == 400
        assert "session_id" in response.json()

    def test_start_transaction_with_missing_connector_id_returns_400(
        self, admin_user_client, remote_command_session
    ):
        request_body = {
            "session_id": remote_command_session.uid,
            "start_kwh": 0,
        }

        response = admin_user_client.post(self.start_transaction_url, data=request_body)

        assert response.status_code == 400
        assert "connector_id" in response.json()

    def test_start_transaction_with_nonexistent_session_id_returns_404(
        self, admin_user_client
    ):
        request_body = {
            "session_id": "NONEXISTENT-SESSION",
            "connector_id": "CONN-1",
            "start_kwh": 0,
        }

        response = admin_user_client.post(self.start_transaction_url, data=request_body)

        assert response.status_code == 404


@pytest.mark.django_db
class TestStopTransactionRemoteCommand:
    stop_transaction_url = reverse("chargepoint-stop-transaction")

    def test_stop_transaction_completes_session_and_returns_200(
        self, admin_user_client, remote_command_session
    ):
        remote_command_session.status = Session.ACTIVE
        remote_command_session.start_kwh = 10.0
        remote_command_session.save()

        request_body = {
            "session_id": remote_command_session.uid,
            "stop_kwh": 50.0,
        }

        response = admin_user_client.post(self.stop_transaction_url, data=request_body)

        assert response.status_code == 200

    def test_stop_transaction_sets_session_to_completed(
        self, admin_user_client, remote_command_session
    ):
        remote_command_session.status = Session.ACTIVE
        remote_command_session.start_kwh = 0.0
        remote_command_session.save()

        request_body = {
            "session_id": remote_command_session.uid,
            "stop_kwh": 30.0,
        }

        response = admin_user_client.post(self.stop_transaction_url, data=request_body)

        assert response.status_code == 200
        remote_command_session.refresh_from_db()
        assert remote_command_session.status == Session.COMPLETED

    def test_stop_transaction_sets_stop_kwh(
        self, admin_user_client, remote_command_session
    ):
        remote_command_session.status = Session.ACTIVE
        remote_command_session.start_kwh = 10.0
        remote_command_session.save()

        expected_stop_kwh = 75.5
        request_body = {
            "session_id": remote_command_session.uid,
            "stop_kwh": expected_stop_kwh,
        }

        response = admin_user_client.post(self.stop_transaction_url, data=request_body)

        assert response.status_code == 200
        remote_command_session.refresh_from_db()
        assert remote_command_session.stop_kwh == expected_stop_kwh

    @time_machine.travel("2025-04-15 14:30:00")
    def test_stop_transaction_sets_end_date_time(
        self, admin_user_client, remote_command_session
    ):
        remote_command_session.status = Session.ACTIVE
        remote_command_session.start_kwh = 5.0
        remote_command_session.save()

        request_body = {
            "session_id": remote_command_session.uid,
            "stop_kwh": 45.0,
        }

        response = admin_user_client.post(self.stop_transaction_url, data=request_body)

        assert response.status_code == 200
        remote_command_session.refresh_from_db()
        assert remote_command_session.end_date_time.replace(microsecond=0) == datetime(
            2025, 4, 15, 14, 30, 0, tzinfo=pytz.utc
        )

    def test_stop_transaction_creates_cdr(
        self, admin_user_client, remote_command_session
    ):
        from ocpi22.models.cdr import Cdr

        remote_command_session.status = Session.ACTIVE
        remote_command_session.start_kwh = 0.0
        remote_command_session.save()

        request_body = {
            "session_id": remote_command_session.uid,
            "stop_kwh": 100.0,
        }

        response = admin_user_client.post(self.stop_transaction_url, data=request_body)

        assert response.status_code == 200
        cdr = Cdr.objects.filter(session_id=remote_command_session.uid).first()
        assert cdr is not None
        assert cdr.session_id == remote_command_session.uid

    def test_stop_transaction_calculates_price(
        self, admin_user_client, remote_command_session
    ):
        remote_command_session.status = Session.ACTIVE
        remote_command_session.start_kwh = 10.0
        remote_command_session.save()

        request_body = {
            "session_id": remote_command_session.uid,
            "stop_kwh": 50.0,
        }

        response = admin_user_client.post(self.stop_transaction_url, data=request_body)

        assert response.status_code == 200
        remote_command_session.refresh_from_db()
        assert remote_command_session.total_cost_incl_vat is not None
        assert remote_command_session.total_cost_excl_vat is not None

    def test_stop_transaction_sends_updates(
        self, admin_user_client, remote_command_session
    ):
        remote_command_session.status = Session.ACTIVE
        remote_command_session.start_kwh = 0.0
        remote_command_session.save()

        request_body = {
            "session_id": remote_command_session.uid,
            "stop_kwh": 80.0,
        }

        with patch.object(Session, "send_updates") as mock_send_updates:
            response = admin_user_client.post(
                self.stop_transaction_url, data=request_body
            )

            assert response.status_code == 200
            mock_send_updates.assert_called_once()

    @time_machine.travel("2025-06-20 10:15:30+00:00", tick=False)
    def test_stop_transaction_returns_session_data(
        self, admin_user_client, remote_command_session
    ):
        from ocpi22.models.cdr import Cdr

        remote_command_session.status = Session.ACTIVE
        remote_command_session.start_kwh = 20.0
        remote_command_session.save()

        request_body = {
            "session_id": remote_command_session.uid,
            "stop_kwh": 70.0,
        }

        with patch.object(Session, "send_updates"):
            response = admin_user_client.post(
                self.stop_transaction_url, data=request_body
            )

            assert response.status_code == 200
            response_data = response.json()

            remote_command_session.refresh_from_db()

            assert response_data["session_id"] == remote_command_session.uid
            assert (
                response_data["billed_to"]
                == f"{remote_command_session.billed_to.country_code}*{remote_command_session.billed_to.party_id}"
            )
            assert response_data["start_kwh"] == remote_command_session.start_kwh
            assert response_data["stop_kwh"] == remote_command_session.stop_kwh
            assert response_data["total_kwh"] == float(remote_command_session.kwh)
            assert response_data["status"] == remote_command_session.status
            assert response_data["auth_method"] == remote_command_session.auth_method
            assert (
                response_data["authorization_reference"]
                == remote_command_session.authorization_reference
            )
            assert response_data["location_id"] == remote_command_session.location.uid
            assert response_data["evse_uid"] == remote_command_session.evse.uid
            assert response_data["connector_id"] == remote_command_session.connector.uid
            assert response_data["currency"] == remote_command_session.currency
            assert response_data[
                "start_date_time"
            ] == remote_command_session.start_date_time.isoformat().replace(
                "+00:00", "Z"
            )
            assert response_data[
                "end_date_time"
            ] == remote_command_session.end_date_time.isoformat().replace("+00:00", "Z")
            assert response_data[
                "last_updated"
            ] == remote_command_session.last_updated.isoformat().replace("+00:00", "Z")
            assert response_data["total_cost_incl_vat"] == float(
                remote_command_session.total_cost_incl_vat
            )
            assert response_data["total_cost_excl_vat"] == float(
                remote_command_session.total_cost_excl_vat
            )
            assert (
                response_data["token"]["token_id"]
                == remote_command_session.cdr_token.uid
            )
            assert (
                response_data["token"]["country_code"]
                == remote_command_session.cdr_token.ocpi_master.country_code
            )
            assert (
                response_data["token"]["party_id"]
                == remote_command_session.cdr_token.ocpi_master.party_id
            )

            cdr = Cdr.objects.filter(session_id=remote_command_session.uid).first()
            assert cdr is not None

    @pytest.mark.parametrize(
        "start_kwh,stop_kwh,expected_total_kwh",
        [
            (0.0, 50.0, 50.0),
            (10.0, 60.0, 50.0),
            (25.5, 100.75, 75.25),
            (100.0, 250.0, 150.0),
        ],
    )
    def test_stop_transaction_calculates_correct_total_kwh(
        self,
        admin_user_client,
        remote_command_session,
        start_kwh,
        stop_kwh,
        expected_total_kwh,
    ):
        remote_command_session.status = Session.ACTIVE
        remote_command_session.start_kwh = start_kwh
        remote_command_session.save()

        request_body = {
            "session_id": remote_command_session.uid,
            "stop_kwh": stop_kwh,
        }

        with patch.object(Session, "send_updates"):
            response = admin_user_client.post(
                self.stop_transaction_url, data=request_body
            )

            assert response.status_code == 200
            response_data = response.json()
            assert response_data["total_kwh"] == expected_total_kwh

    def test_stop_transaction_when_already_completed_returns_409(
        self, admin_user_client, remote_command_session
    ):
        remote_command_session.status = Session.COMPLETED
        remote_command_session.start_kwh = 0.0
        remote_command_session.stop_kwh = 50.0
        remote_command_session.save()

        request_body = {
            "session_id": remote_command_session.uid,
            "stop_kwh": 50.0,
        }

        response = admin_user_client.post(self.stop_transaction_url, data=request_body)

        assert response.status_code == 409
        assert response.json() == {
            "status_text": "Session was completed earlier, cannot stop it twice"
        }

    def test_stop_transaction_with_missing_session_id_returns_400(
        self, admin_user_client
    ):
        request_body = {
            "stop_kwh": 50.0,
        }

        response = admin_user_client.post(self.stop_transaction_url, data=request_body)

        assert response.status_code == 400
        assert "session_id" in response.json()

    def test_stop_transaction_with_missing_stop_kwh_returns_400(
        self, admin_user_client, remote_command_session
    ):
        remote_command_session.status = Session.ACTIVE
        remote_command_session.save()

        request_body = {
            "session_id": remote_command_session.uid,
        }

        response = admin_user_client.post(self.stop_transaction_url, data=request_body)

        assert response.status_code == 400
        assert "stop_kwh" in response.json()

    def test_stop_transaction_with_nonexistent_session_id_returns_404(
        self, admin_user_client
    ):
        request_body = {
            "session_id": "NONEXISTENT-SESSION",
            "stop_kwh": 50.0,
        }

        response = admin_user_client.post(self.stop_transaction_url, data=request_body)

        assert response.status_code == 404

    @pytest.mark.parametrize(
        "invalid_stop_kwh",
        [-1.0, -10.5, "invalid"],
    )
    def test_stop_transaction_with_invalid_stop_kwh_returns_400(
        self, admin_user_client, remote_command_session, invalid_stop_kwh
    ):
        remote_command_session.status = Session.ACTIVE
        remote_command_session.start_kwh = 0.0
        remote_command_session.save()

        request_body = {
            "session_id": remote_command_session.uid,
            "stop_kwh": invalid_stop_kwh,
        }

        response = admin_user_client.post(self.stop_transaction_url, data=request_body)

        assert response.status_code == 400

    def test_stop_transaction_with_non_command_auth_method_completes_session_normally(
        self, admin_user_client, remote_command_session
    ):
        remote_command_session.auth_method = AuthMethodChoices.AUTH_REQUEST
        remote_command_session.status = Session.ACTIVE
        remote_command_session.save()

        request_body = {
            "session_id": remote_command_session.uid,
            "stop_kwh": 60.0,
        }

        response = admin_user_client.post(self.stop_transaction_url, data=request_body)

        assert response.status_code == 200
        remote_command_session.refresh_from_db()
        assert remote_command_session.status == Session.COMPLETED

    def test_stop_transaction_when_session_invalid_returns_409(
        self, admin_user_client, remote_command_session
    ):
        remote_command_session.status = Session.INVALID
        remote_command_session.save()

        request_body = {
            "session_id": remote_command_session.uid,
            "stop_kwh": 50.0,
        }

        response = admin_user_client.post(self.stop_transaction_url, data=request_body)

        assert response.status_code == 409

    def test_stop_transaction_creates_cdr_with_correct_location_data(
        self, admin_user_client, remote_command_session
    ):
        from ocpi22.models.cdr import Cdr

        remote_command_session.status = Session.ACTIVE
        remote_command_session.start_kwh = 0.0
        remote_command_session.save()

        request_body = {
            "session_id": remote_command_session.uid,
            "stop_kwh": 100.0,
        }

        response = admin_user_client.post(self.stop_transaction_url, data=request_body)

        assert response.status_code == 200
        cdr = Cdr.objects.filter(session_id=remote_command_session.uid).first()
        assert cdr is not None
        assert cdr.cdr_location.uid == remote_command_session.location.uid

    def test_stop_transaction_calculates_accurate_energy_consumption(
        self, admin_user_client, remote_command_session
    ):
        remote_command_session.status = Session.ACTIVE
        remote_command_session.start_kwh = 23.5
        remote_command_session.save()

        request_body = {
            "session_id": remote_command_session.uid,
            "stop_kwh": 87.25,
        }

        response = admin_user_client.post(self.stop_transaction_url, data=request_body)

        assert response.status_code == 200
        remote_command_session.refresh_from_db()
        assert remote_command_session.kwh == 63.75

    def test_stop_transaction_with_zero_energy_consumption_succeeds(
        self, admin_user_client, remote_command_session
    ):
        remote_command_session.status = Session.ACTIVE
        remote_command_session.start_kwh = 50.0
        remote_command_session.save()

        request_body = {
            "session_id": remote_command_session.uid,
            "stop_kwh": 50.0,
        }

        response = admin_user_client.post(self.stop_transaction_url, data=request_body)

        assert response.status_code == 200
        remote_command_session.refresh_from_db()
        assert remote_command_session.kwh == 0
