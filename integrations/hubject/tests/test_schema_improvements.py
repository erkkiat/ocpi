import pytest
from datetime import datetime, timedelta
import pytz
from pydantic import ValidationError

from integrations.hubject.schemas import (
    Identification,
    RFIDMifareFamilyIdentificationClass,
    UID,
    ERoamingChargingNotificationStart,
    ERoamingChargingNotificationProgress,
    ERoamingChargingNotificationEnd,
    ChargingNotificationType,
    SessionID,
    EvseID,
    OperatorID,
)


class TestIdentificationValidation:
    def test_identification_with_rfid_mifare_family_succeeds(self):
        identification = Identification(
            RFIDMifareFamilyIdentification=RFIDMifareFamilyIdentificationClass(
                UID=UID(root="7568290FFF765F")
            ),
            RemoteIdentification=None,
            QRCodeIdentification=None,
            RFIDIdentification=None,
            PlugAndChargeIdentification=None,
        )
        assert identification.RFIDMifareFamilyIdentification is not None


class TestChargingNotificationStart:
    @staticmethod
    def create_valid_charging_notification_start(**overrides):
        defaults = {
            "session_id": SessionID(root="b2688855-7f00-0002-6d8e-48d883f6abb6"),
            "evse_id": EvseID(root="DE*ABC*E123*456"),
            "charging_start": datetime.now(pytz.utc),
            "operator_id": OperatorID(root="DE*ABC"),
            "identification": Identification(
                RFIDMifareFamilyIdentification=RFIDMifareFamilyIdentificationClass(
                    UID=UID(root="7568290FFF765F")
                ),
                RemoteIdentification=None,
                QRCodeIdentification=None,
                RFIDIdentification=None,
                PlugAndChargeIdentification=None,
            ),
        }
        defaults.update(overrides)
        return ERoamingChargingNotificationStart(**defaults)

    def test_valid_charging_notification_start_succeeds(self):
        notification = self.create_valid_charging_notification_start()
        assert notification.type == ChargingNotificationType.Start
        assert notification.session_id is not None

    def test_charging_notification_start_with_session_start_before_charging_start_succeeds(
        self,
    ):
        now = datetime.now(pytz.utc)
        notification = self.create_valid_charging_notification_start(
            session_start=now - timedelta(minutes=5), charging_start=now
        )
        assert notification.session_start < notification.charging_start

    def test_charging_notification_start_with_session_start_after_charging_start_raises_validation_error(
        self,
    ):
        now = datetime.now(pytz.utc)
        with pytest.raises(
            ValidationError, match="SessionStart cannot be after ChargingStart"
        ):
            self.create_valid_charging_notification_start(
                session_start=now, charging_start=now - timedelta(minutes=5)
            )

    def test_charging_notification_start_with_negative_meter_value_fails(self):
        with pytest.raises(
            ValidationError, match="Input should be greater than or equal"
        ):
            self.create_valid_charging_notification_start(meter_value_start=-10.0)

    def test_charging_notification_start_with_valid_meter_value_succeeds(self):
        notification = self.create_valid_charging_notification_start(
            meter_value_start=100.0
        )
        assert notification.meter_value_start == 100.0

    def test_charging_notification_start_with_identification_succeeds(self):
        identification = Identification(
            RFIDMifareFamilyIdentification=RFIDMifareFamilyIdentificationClass(
                UID=UID(root="7568290FFF765F")
            ),
            RemoteIdentification=None,
            QRCodeIdentification=None,
            RFIDIdentification=None,
            PlugAndChargeIdentification=None,
        )
        notification = self.create_valid_charging_notification_start(
            identification=identification
        )
        assert notification.identification is not None


class TestChargingNotificationProgress:
    def create_valid_notification_progress(self, **overrides):
        now = datetime.now(pytz.utc)
        defaults = {
            "session_id": SessionID(root="b2688855-7f00-0002-6d8e-48d883f6abb6"),
            "evse_id": EvseID(root="DE*ABC*E123*456"),
            "charging_start": now,
            "event_occurred": now + timedelta(minutes=30),
            "consumed_energy_progress": 25.0,
            "operator_id": OperatorID(root="DE*ABC"),
        }
        defaults.update(overrides)
        return ERoamingChargingNotificationProgress(**defaults)

    def test_valid_charging_notification_progress_with_energy_succeeds(self):
        notification = self.create_valid_notification_progress()
        assert notification.type == ChargingNotificationType.Progress
        assert notification.consumed_energy_progress == 25.0

    def test_valid_charging_notification_progress_with_duration_succeeds(self):
        notification = self.create_valid_notification_progress(
            consumed_energy_progress=None,
            charging_duration=1800000,  # 30 minutes in milliseconds
        )
        assert notification.charging_duration == 1800000

    def test_charging_notification_progress_without_energy_or_duration_fails(self):
        with pytest.raises(
            ValidationError,
            match="Either ChargingDuration or ConsumedEnergyProgress must be provided",
        ):
            self.create_valid_notification_progress(
                consumed_energy_progress=None, charging_duration=None
            )

    def test_charging_notification_progress_with_event_before_charging_start_fails(
        self,
    ):
        now = datetime.now(pytz.utc)
        with pytest.raises(
            ValidationError, match="EventOccurred must be after ChargingStart"
        ):
            self.create_valid_notification_progress(
                charging_start=now, event_occurred=now - timedelta(minutes=5)
            )

    def test_charging_notification_progress_with_negative_energy_fails(self):
        with pytest.raises(
            ValidationError, match="Input should be greater than or equal"
        ):
            self.create_valid_notification_progress(consumed_energy_progress=-10.0)

    def test_charging_notification_progress_with_negative_meter_start_fails(self):
        with pytest.raises(
            ValidationError, match="Input should be greater than or equal"
        ):
            self.create_valid_notification_progress(meter_value_start=-5.0)


class TestChargingNotificationEnd:
    @staticmethod
    def create_valid_notification_end(**overrides):
        now = datetime.now(pytz.utc)
        defaults = {
            "session_id": SessionID(root="b2688855-7f00-0002-6d8e-48d883f6abb6"),
            "evse_id": EvseID(root="DE*ABC*E123*456"),
            "charging_start": now - timedelta(minutes=5),
            "charging_end": now,
            "operator_id": OperatorID(root="DE*ABC"),
        }
        defaults.update(overrides)
        return ERoamingChargingNotificationEnd(**defaults)

    def test_valid_charging_notification_end_succeeds(self):
        notification = self.create_valid_notification_end()
        assert notification.type == ChargingNotificationType.End
        assert notification.charging_end is not None

    def test_charging_notification_end_with_valid_time_sequence_succeeds(self):
        now = datetime.now(pytz.utc)
        notification = self.create_valid_notification_end(
            session_start=now - timedelta(minutes=50),
            charging_start=now - timedelta(minutes=45),
            charging_end=now - timedelta(minutes=10),
            session_end=now - timedelta(minutes=5),
        )
        assert (
            notification.session_start
            < notification.charging_start
            < notification.charging_end
            < notification.session_end
        )

    def test_charging_notification_end_with_charging_start_after_end_fails(self):
        now = datetime.now(pytz.utc)
        with pytest.raises(
            ValidationError,
            match="ChargingStart cannot be after ChargingEnd",
        ):
            self.create_valid_notification_end(
                charging_start=now, charging_end=now - timedelta(minutes=30)
            )

    def test_charging_notification_end_with_session_start_after_session_end_fails(self):
        now = datetime.now(pytz.utc)
        with pytest.raises(
            ValidationError, match="SessionStart cannot be after SessionEnd"
        ):
            self.create_valid_notification_end(
                session_start=now,
                session_end=now - timedelta(minutes=30),
                charging_start=now,
            )

    def test_charging_notification_end_with_session_start_after_charging_start_fails(
        self,
    ):
        now = datetime.now(pytz.utc)
        with pytest.raises(
            ValidationError,
            match="SessionStart cannot be after ChargingStart",
        ):
            self.create_valid_notification_end(
                session_start=now, charging_start=now - timedelta(minutes=5)
            )

    def test_charging_notification_end_with_charging_end_after_session_end_fails(self):
        now = datetime.now(pytz.utc)
        with pytest.raises(
            ValidationError, match="ChargingEnd cannot be after SessionEnd"
        ):
            self.create_valid_notification_end(
                charging_end=now, session_end=now - timedelta(minutes=5)
            )

    def test_charging_notification_end_with_consistent_energy_calculation_succeeds(
        self,
    ):
        notification = self.create_valid_notification_end(
            meter_value_start=100.0, meter_value_end=150.0, consumed_energy=50.0
        )
        assert notification.consumed_energy == 50.0

    def test_charging_notification_end_with_inconsistent_energy_calculation_fails(self):
        with pytest.raises(
            ValidationError, match="ConsumedEnergy.*doesn't match.*meter difference"
        ):
            self.create_valid_notification_end(
                meter_value_start=100.0,
                meter_value_end=150.0,
                consumed_energy=40.0,  # Should be 50.0
            )

    def test_charging_notification_end_with_negative_meter_values_fail(self):
        with pytest.raises(ValidationError, match="Input should be greater than"):
            self.create_valid_notification_end(meter_value_start=-10.0)

        with pytest.raises(ValidationError, match="Input should be greater than"):
            self.create_valid_notification_end(meter_value_end=-10.0)

        with pytest.raises(ValidationError, match="Input should be greater than"):
            self.create_valid_notification_end(consumed_energy=-10.0)

    def test_charging_notification_end_with_penalty_time_before_charging_end_fails(
        self,
    ):
        now = datetime.now(pytz.utc)
        with pytest.raises(
            ValidationError,
            match="PenaltyTimeStart should be after or equal to ChargingEnd",
        ):
            self.create_valid_notification_end(
                charging_end=now, penalty_time_start=now - timedelta(minutes=5)
            )

    def test_charging_notification_end_with_penalty_time_after_charging_end_succeeds(
        self,
    ):
        now = datetime.now(pytz.utc)
        notification = self.create_valid_notification_end(
            charging_end=now, penalty_time_start=now + timedelta(minutes=15)
        )
        assert notification.penalty_time_start > notification.charging_end


class TestEdgeCases:
    def test_charging_notification_with_same_datetime_values_succeeds(self):
        now = datetime.now(pytz.utc)
        notification = ERoamingChargingNotificationEnd(
            session_id=SessionID(root="b2688855-7f00-0002-6d8e-48d883f6abb6"),
            evse_id=EvseID(root="DE*ABC*E123*456"),
            charging_start=now,
            charging_end=now,  # Same time - should be valid
            operator_id=OperatorID(root="DE*ABC"),
        )
        assert notification.charging_start == notification.charging_end
