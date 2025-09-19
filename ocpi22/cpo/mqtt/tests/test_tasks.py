from unittest.mock import patch

import pytest

from ocpi22.cpo.mqtt.tasks import (
    _get_country_and_party_id,
    _format_evse_id,
    save_and_send_evse_status_updates,
)
from ocpi22.models.location import Evse
from ocpi22.tests.factories import EvseFactory, LocationFactory, CredentialsRoleFactory


class TestMqttTasks:
    @pytest.fixture
    def create_evse(self):
        def _create_evse(uid, status):
            credentialsrole = CredentialsRoleFactory(
                country_code="FI", role="CPO", party_id="CPO"
            )
            location = LocationFactory(ocpi_master=credentialsrole)
            evse = EvseFactory(uid=uid, location=location, status=status)
            return evse

        yield _create_evse
        Evse.objects.all().delete()

    def test_get_country_code_and_party_id(self, monkeypatch):
        monkeypatch.setenv("CPO", "FI*CPO")
        country_code, party_id = _get_country_and_party_id()
        assert country_code == "FI"
        assert party_id == "CPO"

    def test_get_country_code_and_party_raises_when_not_set(self, monkeypatch):
        monkeypatch.delenv("CPO", raising=False)
        with pytest.raises(ValueError):
            _get_country_and_party_id()

    def test_format_evse_id(self, monkeypatch):
        country_code, party_id = _get_country_and_party_id()
        evse_id = _format_evse_id(country_code, party_id, "100000001")
        assert evse_id == "FI*CPO*E100000001"

    def test_save_and_send_evse_status_exits_gracefully_when_evse_not_found(
        self, monkeypatch, db
    ):
        monkeypatch.setenv("CPO", "FI*CPO")
        with patch(
            "ocpi22.locations.services.EvseServices.send_status_updates"
        ) as mock_send_status_updates:
            save_and_send_evse_status_updates("100000002", "Available")
            mock_send_status_updates.assert_not_called()

    def test_save_and_send_evse_status_updates_saves_status(
        self, monkeypatch, db, create_evse
    ):
        monkeypatch.setenv("CPO", "FI*CPO")
        evse = create_evse(uid="100000003", status="AVAILABLE")
        save_and_send_evse_status_updates("100000003", "CHARGING")
        evse.refresh_from_db()
        assert evse.status == "CHARGING"

    def test_save_and_send_evse_status_updates_calls_send_status_updates(
        self, monkeypatch, db, create_evse
    ):
        evse = create_evse(uid="100000004", status="RESERVED")
        monkeypatch.setenv("CPO", "FI*CPO")
        with patch(
            "ocpi22.locations.services.EvseServices.send_status_updates"
        ) as mock_send_status_updates:
            save_and_send_evse_status_updates.run("100000004", "AVAILABLE")
            evse.refresh_from_db()
            assert evse.status == "AVAILABLE"
            mock_send_status_updates.assert_called_once()
