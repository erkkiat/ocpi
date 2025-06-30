import pytest
from datetime import datetime, timedelta
import pytz
from pydantic import ValidationError

from integrations.hubject.schemas import (
    IdentificationClass,
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
from integrations.hubject.services import (
    validate_meter_values,
)


class TestIdentificationValidation:
    """Test the improved Identification validation with mutual exclusion."""

    def test_identification_with_rfid_mifare_family_succeeds(self):
        """Test that a valid RFID Mifare Family identification is accepted."""
        identification = IdentificationClass(
            RFIDMifareFamilyIdentification=RFIDMifareFamilyIdentificationClass(
                UID=UID(root="7568290FFF765F")
            )
        )
        assert identification.RFIDMifareFamilyIdentification is not None


class TestChargingNotificationStart:
    """Test the enhanced ERoamingChargingNotificationStart validation."""

    @staticmethod
    def create_valid_notification_start(**overrides):
        """Helper to create a valid charging notification start."""
        defaults = {
            "SessionID": SessionID(root="b2688855-7f00-0002-6d8e-48d883f6abb6"),
            "EvseID": EvseID(root="DE*ABC*E123*456"),
            "ChargingStart": datetime.now(pytz.utc),
            "OperatorID": OperatorID(root="DE*ABC"),
            "Identification": IdentificationClass(
                RFIDMifareFamilyIdentification=RFIDMifareFamilyIdentificationClass(
                    UID=UID(root="7568290FFF765F")
                )
            ),
        }
        defaults.update(overrides)
        return ERoamingChargingNotificationStart(**defaults)

    def test_valid_charging_notification_start_succeeds(self):
        """Test that a valid charging notification start is accepted."""
        notification = self.create_valid_notification_start()
        assert notification.Type == ChargingNotificationType.Start
        assert notification.SessionID is not None

    def test_charging_notification_start_with_session_start_before_charging_start_succeeds(
        self,
    ):
        """Test that SessionStart before ChargingStart is valid."""
        now = datetime.now(pytz.utc)
        notification = self.create_valid_notification_start(
            SessionStart=now - timedelta(minutes=5), ChargingStart=now
        )
        assert notification.SessionStart < notification.ChargingStart

    def test_charging_notification_start_with_session_start_after_charging_start_fails(
        self,
    ):
        """Test that SessionStart after ChargingStart fails validation."""
        now = datetime.now(pytz.utc)
        with pytest.raises(
            ValidationError, match="SessionStart cannot be after ChargingStart"
        ):
            self.create_valid_notification_start(
                SessionStart=now, ChargingStart=now - timedelta(minutes=5)
            )

    def test_charging_notification_start_with_negative_meter_value_fails(self):
        """Test that negative MeterValueStart fails validation."""
        with pytest.raises(
            ValidationError, match="Input should be greater than or equal"
        ):
            self.create_valid_notification_start(MeterValueStart=-10.0)

    def test_charging_notification_start_with_valid_meter_value_succeeds(self):
        """Test that positive MeterValueStart succeeds."""
        notification = self.create_valid_notification_start(MeterValueStart=100.0)
        assert notification.MeterValueStart == 100.0

    def test_charging_notification_start_with_identification_succeeds(self):
        """Test that adding identification works properly."""
        identification = IdentificationClass(
            RFIDMifareFamilyIdentification=RFIDMifareFamilyIdentificationClass(
                UID=UID(root="7568290FFF765F")
            )
        )
        notification = self.create_valid_notification_start(
            Identification=identification
        )
        assert notification.Identification is not None


class TestChargingNotificationProgress:
    """Test the enhanced ERoamingChargingNotificationProgress validation."""

    def create_valid_notification_progress(self, **overrides):
        """Helper to create a valid charging notification progress."""
        now = datetime.now(pytz.utc)
        defaults = {
            "SessionID": SessionID(root="b2688855-7f00-0002-6d8e-48d883f6abb6"),
            "EvseID": EvseID(root="DE*ABC*E123*456"),
            "ChargingStart": now,
            "EventOccurred": now + timedelta(minutes=30),
            "ConsumedEnergyProgress": 25.0,
            "OperatorID": OperatorID(root="DE*ABC"),
        }
        defaults.update(overrides)
        return ERoamingChargingNotificationProgress(**defaults)

    def test_valid_charging_notification_progress_with_energy_succeeds(self):
        """Test that a valid progress notification with energy succeeds."""
        notification = self.create_valid_notification_progress()
        assert notification.Type == ChargingNotificationType.Progress
        assert notification.ConsumedEnergyProgress == 25.0

    def test_valid_charging_notification_progress_with_duration_succeeds(self):
        """Test that a valid progress notification with duration succeeds."""
        notification = self.create_valid_notification_progress(
            ConsumedEnergyProgress=None,
            ChargingDuration=1800000,  # 30 minutes in milliseconds
        )
        assert notification.ChargingDuration == 1800000

    def test_charging_notification_progress_without_energy_or_duration_fails(self):
        """Test that progress notification without energy or duration fails."""
        with pytest.raises(
            ValidationError,
            match="Either ChargingDuration or ConsumedEnergyProgress must be provided",
        ):
            self.create_valid_notification_progress(
                ConsumedEnergyProgress=None, ChargingDuration=None
            )

    def test_charging_notification_progress_with_event_before_charging_start_fails(
        self,
    ):
        """Test that EventOccurred before ChargingStart fails."""
        now = datetime.now(pytz.utc)
        with pytest.raises(
            ValidationError, match="EventOccurred must be after ChargingStart"
        ):
            self.create_valid_notification_progress(
                ChargingStart=now, EventOccurred=now - timedelta(minutes=5)
            )

    def test_charging_notification_progress_with_negative_energy_fails(self):
        """Test that negative consumed energy fails validation."""
        with pytest.raises(
            ValidationError, match="Input should be greater than or equal"
        ):
            self.create_valid_notification_progress(ConsumedEnergyProgress=-10.0)

    def test_charging_notification_progress_with_negative_meter_start_fails(self):
        """Test that negative meter start value fails validation."""
        with pytest.raises(
            ValidationError, match="Input should be greater than or equal"
        ):
            self.create_valid_notification_progress(MeterValueStart=-5.0)


class TestChargingNotificationEnd:
    """Test the enhanced ERoamingChargingNotificationEnd validation."""

    def create_valid_notification_end(self, **overrides):
        """Helper to create a valid charging notification end."""
        now = datetime.now(pytz.utc)
        defaults = {
            "SessionID": SessionID(root="b2688855-7f00-0002-6d8e-48d883f6abb6"),
            "EvseID": EvseID(root="DE*ABC*E123*456"),
            "ChargingEnd": now,
            "OperatorID": OperatorID(root="DE*ABC"),
        }
        defaults.update(overrides)
        return ERoamingChargingNotificationEnd(**defaults)

    def test_valid_charging_notification_end_succeeds(self):
        """Test that a valid charging notification end is accepted."""
        notification = self.create_valid_notification_end()
        assert notification.Type == ChargingNotificationType.End
        assert notification.ChargingEnd is not None

    def test_charging_notification_end_with_valid_time_sequence_succeeds(self):
        """Test that valid time sequence is accepted."""
        now = datetime.now(pytz.utc)
        notification = self.create_valid_notification_end(
            SessionStart=now - timedelta(minutes=5),
            ChargingStart=now,
            ChargingEnd=now + timedelta(hours=1),
            SessionEnd=now + timedelta(hours=1, minutes=2),
        )
        assert (
            notification.SessionStart
            < notification.ChargingStart
            < notification.ChargingEnd
            < notification.SessionEnd
        )

    def test_charging_notification_end_with_charging_start_after_end_fails(self):
        """Test that ChargingStart after ChargingEnd fails."""
        now = datetime.now(pytz.utc)
        with pytest.raises(
            ValidationError, match="ChargingStart cannot be after ChargingEnd"
        ):
            self.create_valid_notification_end(
                ChargingStart=now, ChargingEnd=now - timedelta(minutes=30)
            )

    def test_charging_notification_end_with_session_start_after_end_fails(self):
        """Test that SessionStart after SessionEnd fails."""
        now = datetime.now(pytz.utc)
        with pytest.raises(
            ValidationError, match="SessionStart cannot be after SessionEnd"
        ):
            self.create_valid_notification_end(
                SessionStart=now, SessionEnd=now - timedelta(minutes=30)
            )

    def test_charging_notification_end_with_session_start_after_charging_start_fails(
        self,
    ):
        """Test that SessionStart after ChargingStart fails."""
        now = datetime.now(pytz.utc)
        with pytest.raises(
            ValidationError,
            match="SessionStart should be before or equal to ChargingStart",
        ):
            self.create_valid_notification_end(
                SessionStart=now, ChargingStart=now - timedelta(minutes=5)
            )

    def test_charging_notification_end_with_charging_end_after_session_end_fails(self):
        """Test that ChargingEnd after SessionEnd fails."""
        now = datetime.now(pytz.utc)
        with pytest.raises(
            ValidationError, match="ChargingEnd should be before or equal to SessionEnd"
        ):
            self.create_valid_notification_end(
                ChargingEnd=now, SessionEnd=now - timedelta(minutes=5)
            )

    def test_charging_notification_end_with_consistent_energy_calculation_succeeds(
        self,
    ):
        """Test that consistent energy calculation succeeds."""
        notification = self.create_valid_notification_end(
            MeterValueStart=100.0, MeterValueEnd=150.0, ConsumedEnergy=50.0
        )
        assert notification.ConsumedEnergy == 50.0

    def test_charging_notification_end_with_inconsistent_energy_calculation_fails(self):
        """Test that inconsistent energy calculation fails."""
        with pytest.raises(
            ValidationError, match="ConsumedEnergy.*doesn't match.*meter difference"
        ):
            self.create_valid_notification_end(
                MeterValueStart=100.0,
                MeterValueEnd=150.0,
                ConsumedEnergy=40.0,  # Should be 50.0
            )

    def test_charging_notification_end_with_negative_meter_values_fail(self):
        with pytest.raises(ValidationError, match="Input should be greater than"):
            self.create_valid_notification_end(MeterValueStart=-10.0)

        with pytest.raises(ValidationError, match="Input should be greater than"):
            self.create_valid_notification_end(MeterValueEnd=-10.0)

        with pytest.raises(ValidationError, match="Input should be greater than"):
            self.create_valid_notification_end(ConsumedEnergy=-10.0)

    def test_charging_notification_end_with_penalty_time_before_charging_end_fails(
        self,
    ):
        now = datetime.now(pytz.utc)
        with pytest.raises(
            ValidationError, match="PenaltyTimeStart should be after ChargingEnd"
        ):
            self.create_valid_notification_end(
                ChargingEnd=now, PenaltyTimeStart=now - timedelta(minutes=5)
            )

    def test_charging_notification_end_with_penalty_time_after_charging_end_succeeds(
        self,
    ):
        """Test that penalty time after charging end succeeds."""
        now = datetime.now(pytz.utc)
        notification = self.create_valid_notification_end(
            ChargingEnd=now, PenaltyTimeStart=now + timedelta(minutes=15)
        )
        assert notification.PenaltyTimeStart > notification.ChargingEnd


class TestUtilityFunctions:
    """Test the utility functions added to services.py."""

    def test_validate_meter_values_valid_succeeds(self):
        validate_meter_values(meter_start=100.0, meter_end=150.0, consumed_energy=50.0)

    def test_validate_meter_values_negative_start_fails(self):
        with pytest.raises(ValueError, match="MeterValueStart cannot be negative"):
            validate_meter_values(meter_start=-10.0)

    def test_validate_meter_values_negative_end_fails(self):
        with pytest.raises(ValueError, match="MeterValueEnd cannot be negative"):
            validate_meter_values(meter_end=-10.0)

    def test_validate_meter_values_negative_consumed_fails(self):
        with pytest.raises(ValueError, match="ConsumedEnergy cannot be negative"):
            validate_meter_values(consumed_energy=-10.0)

    def test_validate_meter_values_inconsistent_calculation_fails(self):
        """Test that inconsistent energy calculation fails."""
        with pytest.raises(
            ValueError, match="ConsumedEnergy.*doesn't match.*meter difference"
        ):
            validate_meter_values(
                meter_start=100.0,
                meter_end=150.0,
                consumed_energy=40.0,  # Should be 50.0
            )

    def test_validate_meter_values_with_tolerance_succeeds(self):
        # Should not raise an exception (within 0.001 tolerance)
        validate_meter_values(
            meter_start=100.0,
            meter_end=150.0,
            consumed_energy=50.0005,  # Very small difference
        )

    def test_validate_meter_values_partial_data_succeeds(self):
        validate_meter_values(meter_start=100.0)
        validate_meter_values(meter_end=150.0)
        validate_meter_values(consumed_energy=50.0)
        validate_meter_values(meter_start=100.0, meter_end=150.0)


class TestEdgeCases:
    def test_charging_notification_with_same_datetime_values_succeeds(self):
        now = datetime.now(pytz.utc)
        notification = ERoamingChargingNotificationEnd(
            SessionID=SessionID(root="b2688855-7f00-0002-6d8e-48d883f6abb6"),
            EvseID=EvseID(root="DE*ABC*E123*456"),
            ChargingStart=now,
            ChargingEnd=now,  # Same time - should be valid
            OperatorID=OperatorID(root="DE*ABC"),
        )
        assert notification.ChargingStart == notification.ChargingEnd

    def test_meter_values_with_zero_consumption_succeeds(self):
        validate_meter_values(meter_start=100.0, meter_end=100.0, consumed_energy=0.0)

    def test_floating_point_precision_in_energy_calculation(self):
        validate_meter_values(
            meter_start=100.123456789,
            meter_end=150.987654321,
            consumed_energy=50.864197532,  # Precise calculation
        )

    def test_large_meter_values_succeed(self):
        validate_meter_values(
            meter_start=999999.999, meter_end=1000099.999, consumed_energy=100.0
        )
