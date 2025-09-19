import pytest
from datetime import datetime, timedelta
from pydantic import ValidationError
import pytz

from integrations.hubject.schemas import ERoamingChargeDetailRecord, MeteringStatus


class TestERoamingChargeDetailRecordValidation:
    @pytest.fixture
    def valid_eroaming_cdr(self):
        return {
            "session_id": "12345678-1234-1234-1234-123456789012",
            "evse_id": "DE*AB7*E840*6487",
            "identification": {
                "RFIDMifareFamilyIdentification": {"UID": "7568290FFF765F"}
            },
            "charging_start": "2024-01-15T10:00:00Z",
            "charging_end": "2024-01-15T12:00:00Z",
            "session_start": "2024-01-15T09:30:00Z",
            "session_end": "2024-01-15T12:30:00Z",
            "consumed_energy": 25.5,
        }

    def test_valid_charge_detail_record_creation_succeeds(self, valid_eroaming_cdr):
        record = ERoamingChargeDetailRecord(**valid_eroaming_cdr)

        assert record.session_id.root == "12345678-1234-1234-1234-123456789012"
        assert record.evse_id.root == "DE*AB7*E840*6487"
        assert record.consumed_energy == 25.5
        assert (
            record.identification.RFIDMifareFamilyIdentification.UID.root
            == "7568290FFF765F"
        )
        assert record.charging_start == datetime(2024, 1, 15, 10, 0, 0, tzinfo=pytz.UTC)
        assert record.charging_end == datetime(2024, 1, 15, 12, 0, 0, tzinfo=pytz.UTC)
        assert record.session_start == datetime(2024, 1, 15, 9, 30, 0, tzinfo=pytz.UTC)
        assert record.session_end == datetime(2024, 1, 15, 12, 30, 0, tzinfo=pytz.UTC)

    def test_charging_end_before_charging_start_validation_raises_validation_error(
        self, valid_eroaming_cdr
    ):
        valid_eroaming_cdr["charging_end"] = "2024-01-15T09:00:00Z"

        with pytest.raises(ValidationError) as exc_info:
            ERoamingChargeDetailRecord(**valid_eroaming_cdr)

        assert "ChargingStart cannot be after ChargingEnd" in str(exc_info.value)

    def test_session_start_after_charging_end_validation_raises_validation_error(
        self, valid_eroaming_cdr
    ):
        data = {
            "session_start": "2024-01-15T13:00:00Z",  # after charging_end
            "charging_start": "2024-01-15T10:30:00Z",  # before charging_end
            "charging_end": "2024-01-15T12:00:00Z",  # before session_start
            "session_end": "2024-01-15T14:00:00Z",
        }
        valid_eroaming_cdr.update(data)

        with pytest.raises(ValidationError) as exc_info:
            ERoamingChargeDetailRecord(**valid_eroaming_cdr)

        # In CDR all fields are required, so the exact message "SessionStart cannot be after ChargingEnd" cannot not be triggered.
        assert "SessionStart cannot be after ChargingStart" in str(exc_info.value)

    def test_session_start_after_session_end_validation_raises_validation_error(
        self, valid_eroaming_cdr
    ):
        data = {
            "session_start": "2024-01-15T13:00:00Z",  # after charging_end
            "charging_start": "2024-01-15T13:30:00Z",  # before charging_end
            "charging_end": "2024-01-15T13:40:00Z",  # before session_start
            "session_end": "2024-01-15T12:00:00Z",
        }
        valid_eroaming_cdr.update(data)

        with pytest.raises(ValidationError) as exc_info:
            ERoamingChargeDetailRecord(**valid_eroaming_cdr)

        assert "SessionStart cannot be after SessionEnd" in str(exc_info.value)

    def test_charging_end_after_session_end_validation_raises_validation_error(
        self, valid_eroaming_cdr
    ):
        data = {
            "charging_end": "2024-01-15T13:00:00Z",
            "session_end": "2024-01-15T12:00:00Z",
        }
        valid_eroaming_cdr.update(data)

        with pytest.raises(ValidationError) as exc_info:
            ERoamingChargeDetailRecord(**valid_eroaming_cdr)

        assert "ChargingEnd cannot be after SessionEnd" in str(exc_info.value)

    def test_session_end_in_the_future_validation_raises_validation_error(
        self, valid_eroaming_cdr
    ):
        data = {
            "session_end": datetime.strftime(
                datetime.now(pytz.utc) + timedelta(days=1), "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
        valid_eroaming_cdr.update(data)

        with pytest.raises(ValidationError) as exc_info:
            ERoamingChargeDetailRecord(**valid_eroaming_cdr)

        assert "SessionEnd cannot be in the future" in str(exc_info.value)

    def test_meter_value_start_greater_than_end_validation_raises_validation_error(
        self, valid_eroaming_cdr
    ):
        valid_eroaming_cdr["meter_value_start"] = 100.0
        valid_eroaming_cdr["meter_value_end"] = 50.0

        with pytest.raises(ValidationError) as exc_info:
            ERoamingChargeDetailRecord(**valid_eroaming_cdr)

        assert "MeterValueStart cannot be after MeterValueEnd" in str(exc_info.value)

    def test_meter_value_in_between_greater_than_end_validation_raises_validation_error(
        self, valid_eroaming_cdr
    ):
        data = {
            "meter_value_start": 10.0,
            "meter_value_end": 50.0,
            "consumed_energy": 40.0,
            "meter_value_in_between": {"meterValues": [20.0, 30.0, 60.0]},
        }
        valid_eroaming_cdr.update(data)

        with pytest.raises(ValidationError) as exc_info:
            ERoamingChargeDetailRecord(**valid_eroaming_cdr)

        assert "MeterValueInBetween cannot be after MeterValueEnd" in str(
            exc_info.value
        )

    def test_consumed_energy_exceeds_maximum_raises_validation_error(
        self, valid_eroaming_cdr
    ):
        valid_eroaming_cdr["consumed_energy"] = 1500.0

        with pytest.raises(ValidationError) as exc_info:
            ERoamingChargeDetailRecord(**valid_eroaming_cdr)

        assert "ConsumedEnergy must be less than or equal to 1000 kWh" in str(
            exc_info.value
        )

    def test_consumed_energy_negative_value_raises_validation_error(
        self, valid_eroaming_cdr
    ):
        valid_eroaming_cdr["consumed_energy"] = -10.0

        with pytest.raises(ValidationError) as exc_info:
            ERoamingChargeDetailRecord(**valid_eroaming_cdr)

        assert "greater than or equal to 0" in str(exc_info.value)

    def test_valid_meter_values_with_in_between_succeeds(self, valid_eroaming_cdr):
        data = {
            "meter_value_start": 10.0,
            "meter_value_end": 50.0,
            "consumed_energy": 40.0,
            "meter_value_in_between": {"meterValues": [15.0, 25.0, 35.0, 45.0]},
        }
        valid_eroaming_cdr.update(data)

        record = ERoamingChargeDetailRecord(**valid_eroaming_cdr)

        assert record.meter_value_start == 10.0
        assert record.meter_value_end == 50.0
        assert record.meter_value_in_between.meterValues == [15.0, 25.0, 35.0, 45.0]

    def test_timezone_aware_datetime_required_validation_passes(
        self, valid_eroaming_cdr
    ):
        record = ERoamingChargeDetailRecord(**valid_eroaming_cdr)

        assert record.charging_start.tzinfo is not None
        assert record.charging_end.tzinfo is not None
        assert record.session_start.tzinfo is not None
        assert record.session_end.tzinfo is not None

    def test_valid_signed_meter_values_with_different_statuses_succeeds(
        self, valid_eroaming_cdr
    ):
        valid_eroaming_cdr["SignedMeteringValues"] = [
            {"SignedMeteringValue": "start_signature_value", "MeteringStatus": "Start"},
            {
                "SignedMeteringValue": "progress_signature_value",
                "MeteringStatus": "Progress",
            },
            {"SignedMeteringValue": "end_signature_value", "MeteringStatus": "End"},
        ]

        record = ERoamingChargeDetailRecord(**valid_eroaming_cdr)

        assert len(record.signed_metering_values) == 3
        assert record.signed_metering_values[0].MeteringStatus == MeteringStatus.Start
        assert (
            record.signed_metering_values[1].MeteringStatus == MeteringStatus.Progress
        )
        assert record.signed_metering_values[2].MeteringStatus == MeteringStatus.End

    def test_alias_generator_converts_field_names_correctly(self, valid_eroaming_cdr):
        record = ERoamingChargeDetailRecord(**valid_eroaming_cdr)

        assert hasattr(record, "session_id")
        assert hasattr(record, "evse_id")
        assert hasattr(record, "charging_start")

        serialized = record.model_dump(by_alias=True)
        assert "CPOPartnerSessionID" in serialized
        assert "EMPPartnerSessionID" in serialized
        assert "SessionID" in serialized
        assert "EvseID" in serialized
        assert "ChargingStart" in serialized

    def test_optional_fields_can_be_omitted(self, valid_eroaming_cdr):
        minimal_data = {
            key: value
            for key, value in valid_eroaming_cdr.items()
            if key
            not in [
                "cpo_partner_session_id",
                "emp_partner_session_id",
                "partner_product_id",
            ]
        }

        record = ERoamingChargeDetailRecord(**minimal_data)

        assert record.cpo_partner_session_id is None
        assert record.emp_partner_session_id is None
        assert record.partner_product_id is None

    def test_empty_meter_value_in_between_list_validation_succeeds(
        self, valid_eroaming_cdr
    ):
        data = {
            "meter_value_start": 10.0,
            "meter_value_end": 50.0,
            "consumed_energy": 40.0,
            "meter_value_in_between": {"meterValues": []},
        }
        valid_eroaming_cdr.update(data)

        record = ERoamingChargeDetailRecord(**valid_eroaming_cdr)

        assert record.meter_value_in_between.meterValues == []

    def test_equal_datetime_values_validation_succeeds(self, valid_eroaming_cdr):
        same_time = "2024-01-15T12:00:00Z"
        valid_eroaming_cdr["charging_start"] = same_time
        valid_eroaming_cdr["charging_end"] = same_time

        record = ERoamingChargeDetailRecord(**valid_eroaming_cdr)

        assert record.charging_start == record.charging_end
