from datetime import datetime
from unittest.mock import patch

import pytest
import time_machine

from integrations.hubject.schemas import ChargingNotificationType
from ocpi22.cpo.mqtt.tasks import (
    _get_country_and_party_id,
    _format_evse_id,
    save_and_send_evse_status_updates,
    update_meter_values_async,
)
from ocpi22.models.location import Evse
from ocpi22.models.session import Session
from ocpi22.tests.factories import (
    EvseFactory,
    LocationFactory,
    CredentialsRoleFactory,
    OCPISessionFactory,
    ConnectorFactory,
    TariffFactory,
)


class TestGetCountryAndPartyId:
    def test_get_country_and_party_id_returns_tuple_when_cpo_set(self, monkeypatch):
        monkeypatch.setenv("CPO", "FI*CPO")
        country_code, party_id = _get_country_and_party_id()

        assert country_code == "FI"
        assert party_id == "CPO"

    def test_get_country_and_party_id_raises_value_error_when_cpo_not_set(
        self, monkeypatch
    ):
        monkeypatch.delenv("CPO", raising=False)

        with pytest.raises(
            ValueError, match="CPO is not set in the environment variables"
        ):
            _get_country_and_party_id()


class TestFormatEvseId:
    def test_format_evse_id_returns_correctly_formatted_string(self):
        evse_id = _format_evse_id("FI", "CPO", "100000001")

        assert evse_id == "FI*CPO*E100000001"

    @pytest.mark.parametrize(
        "country,party,uid,expected",
        [
            ("DE", "ABC", "12345", "DE*ABC*E12345"),
            ("NL", "XYZ", "999", "NL*XYZ*E999"),
            ("BE", "EMO", "00001", "BE*EMO*E00001"),
        ],
    )
    def test_format_evse_id_handles_various_inputs(self, country, party, uid, expected):
        evse_id = _format_evse_id(country, party, uid)

        assert evse_id == expected


class TestSaveAndSendEvseStatusUpdates:
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

    def test_save_and_send_evse_status_updates_exits_gracefully_when_evse_not_found(
        self, monkeypatch, db
    ):
        monkeypatch.setenv("CPO", "FI*CPO")

        with patch(
            "ocpi22.locations.services.EvseServices.send_status_updates"
        ) as mock_send_status_updates:
            save_and_send_evse_status_updates("100000002", "Available")

            mock_send_status_updates.assert_not_called()

    def test_save_and_send_evse_status_updates_saves_status_to_database(
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


class TestUpdateMeterValuesAsync:
    @pytest.fixture
    def mock_update_meter_values_calls(self, monkeypatch):
        calls = []

        def mock_update_meter_values(*args, **kwargs):
            calls.append(kwargs)

        monkeypatch.setattr(
            "ocpi22.cpo.session_service.SessionService.update_meter_values",
            mock_update_meter_values,
        )
        return calls

    @pytest.mark.django_db
    def test_update_meter_values_async_exits_early_when_session_not_found(self, caplog):
        caplog.set_level("WARNING", logger="ocpi22.cpo.mqtt.tasks")

        update_meter_values_async(
            session_id="non-existent-session",
            timestamp="2024-01-15T10:00:00+00:00",
            kwh=10.5,
            soc=50.0,
            power=22.0,
        )

        assert any(
            "No session found for session_id: non-existent-session" in record.message
            for record in caplog.records
        )

    @pytest.mark.django_db
    def test_update_meter_values_async_skips_processing_when_session_not_active(
        self, caplog
    ):
        caplog.set_level("INFO", logger="ocpi22.cpo.mqtt.tasks")
        session = OCPISessionFactory(status=Session.PENDING)

        update_meter_values_async(
            session_id=session.uid,
            timestamp="2024-01-15T10:00:00+00:00",
            kwh=10.5,
            soc=50.0,
            power=22.0,
        )

        assert any(
            f"Meter values received for non-active session: {session.uid}"
            in record.message
            and session.status in record.message
            for record in caplog.records
        )

    @pytest.mark.django_db
    @time_machine.travel("2024-01-15 12:00:00", tick=False)
    def test_update_meter_values_async_updates_session_with_correct_values(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            status=Session.ACTIVE,
            connector=connector,
            start_kwh=10.0,
        )

        with patch.object(session, "send_updates"):
            update_meter_values_async(
                session_id=session.uid,
                timestamp="2024-01-15T10:30:45+00:00",
                kwh=15.75,
                soc=60.5,
                power=11.0,
            )

            session.refresh_from_db()
            assert session.start_kwh == 10.0
            assert session.stop_kwh == 15.75

    @pytest.mark.django_db
    def test_update_meter_values_async_calls_send_updates_after_successful_update(
        self,
    ):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            status=Session.ACTIVE,
            connector=connector,
        )

        with patch.object(Session, "send_updates") as mock_send_updates:
            update_meter_values_async(
                session_id=session.uid,
                timestamp="2024-01-15T10:30:45+00:00",
                kwh=15.75,
                soc=60.5,
                power=11.0,
            )

            mock_send_updates.assert_called_once_with(
                method="put", update_type=ChargingNotificationType.Progress
            )

    @pytest.mark.django_db
    def test_update_meter_values_async_handles_exception_gracefully(
        self, caplog, monkeypatch
    ):
        caplog.set_level("WARNING", logger="ocpi22.cpo.mqtt.tasks")
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            status=Session.ACTIVE,
            connector=connector,
        )

        def raise_exception(*args, **kwargs):
            raise Exception("Database error")

        monkeypatch.setattr(
            "ocpi22.cpo.session_service.SessionService.update_meter_values",
            raise_exception,
        )

        update_meter_values_async(
            session_id=session.uid,
            timestamp="2024-01-15T10:30:45+00:00",
            kwh=15.75,
            soc=60.5,
            power=11.0,
        )

        assert any(
            f"Failed to process meter values for session {session.uid}"
            in record.message
            for record in caplog.records
        )

    @pytest.mark.django_db
    def test_update_meter_values_async_does_not_call_send_updates_when_exception_occurs(
        self, monkeypatch
    ):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            status=Session.ACTIVE,
            connector=connector,
        )

        def raise_exception(*args, **kwargs):
            raise Exception("Database error")

        monkeypatch.setattr(
            "ocpi22.cpo.session_service.SessionService.update_meter_values",
            raise_exception,
        )

        with patch.object(session, "send_updates") as mock_send_updates:
            update_meter_values_async(
                session_id=session.uid,
                timestamp="2024-01-15T10:30:45+00:00",
                kwh=15.75,
                soc=60.5,
                power=11.0,
            )

            mock_send_updates.assert_not_called()

    @pytest.mark.django_db
    @time_machine.travel("2024-01-15 14:30:00", tick=False)
    def test_update_meter_values_async_successfully_processes_complete_flow(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            status=Session.ACTIVE,
            connector=connector,
            start_kwh=5.0,
        )

        update_meter_values_async(
            session_id=session.uid,
            timestamp="2024-01-15T14:25:00+00:00",
            kwh=12.5,
            soc=75.0,
            power=7.4,
        )

        session.refresh_from_db()
        assert session.start_kwh == 5.0
        assert session.stop_kwh == 12.5

    @pytest.mark.django_db
    def test_update_meter_values_async_handles_none_values_for_optional_fields(
        self, mock_update_meter_values_calls
    ):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            status=Session.ACTIVE,
            connector=connector,
        )

        with patch.object(session, "send_updates"):
            update_meter_values_async(
                session_id=session.uid,
                timestamp="2024-01-15T10:30:45+00:00",
                kwh=15.75,
                soc=None,
                power=None,
            )

            assert len(mock_update_meter_values_calls) == 1
            call_kwargs = mock_update_meter_values_calls[0]
            assert call_kwargs["soc"] is None
            assert call_kwargs["power"] is None

    @pytest.mark.django_db
    def test_update_meter_values_async_logs_success_message_after_processing(
        self, caplog, monkeypatch
    ):
        caplog.set_level("INFO", logger="ocpi22.cpo.mqtt.tasks")
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            status=Session.ACTIVE,
            connector=connector,
        )

        def mock_update_meter_values(*args, **kwargs):
            pass

        monkeypatch.setattr(
            "ocpi22.cpo.session_service.SessionService.update_meter_values",
            mock_update_meter_values,
        )

        with patch.object(session, "send_updates"):
            update_meter_values_async(
                session_id=session.uid,
                timestamp="2024-01-15T10:30:45+00:00",
                kwh=15.75,
                soc=60.5,
                power=11.0,
            )

            assert any(
                f"Successfully processed meter values for session {session.uid}"
                in record.message
                for record in caplog.records
            )

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "kwh,soc,power",
        [
            (10.5, 50.0, 22.0),
            (0.0, 0.0, 0.0),
            (100.5, 100.0, 50.0),
            (5.25, None, 11.0),
            (15.0, 80.0, None),
        ],
    )
    def test_update_meter_values_async_handles_various_meter_value_combinations(
        self, kwh, soc, power, mock_update_meter_values_calls
    ):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            status=Session.ACTIVE,
            connector=connector,
        )

        with patch.object(session, "send_updates"):
            update_meter_values_async(
                session_id=session.uid,
                timestamp="2024-01-15T10:30:45+00:00",
                kwh=kwh,
                soc=soc,
                power=power,
            )

            assert len(mock_update_meter_values_calls) == 1
            call_kwargs = mock_update_meter_values_calls[0]
            assert call_kwargs["kwh"] == kwh
            assert call_kwargs["soc"] == soc
            assert call_kwargs["power"] == power

    @pytest.mark.django_db
    def test_update_meter_values_async_converts_timestamp_string_to_datetime(
        self, mock_update_meter_values_calls
    ):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            status=Session.ACTIVE,
            connector=connector,
        )

        with patch.object(session, "send_updates"):
            update_meter_values_async(
                session_id=session.uid,
                timestamp="2024-01-15T10:30:45+00:00",
                kwh=15.75,
            )

            assert len(mock_update_meter_values_calls) == 1
            call_kwargs = mock_update_meter_values_calls[0]
            assert call_kwargs["timestamp"] == datetime.fromisoformat(
                "2024-01-15T10:30:45+00:00"
            )
