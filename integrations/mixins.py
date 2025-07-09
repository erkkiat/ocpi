from datetime import datetime

import pytz
from pydantic import model_validator


class ConsumedEnergyValidatorMixin:
    @model_validator(mode="after")
    @classmethod
    def validate_consumed_energy(cls, values):
        consumed_energy = values.consumed_energy
        meter_value_start = values.meter_value_start
        meter_value_end = values.meter_value_end
        if consumed_energy is not None and consumed_energy > 1000.0:
            raise ValueError("ConsumedEnergy must be less than or equal to 1000 kWh")
        if (
            meter_value_start is not None
            and meter_value_end is not None
            and consumed_energy is not None
        ):
            expected = meter_value_end - meter_value_start
            if abs(consumed_energy - expected) > 0.001:
                raise ValueError(
                    f"ConsumedEnergy ({consumed_energy}) doesn't match "
                    f"meter difference ({expected})"
                )
        return values


class ChargingStartValidatorMixin:
    @model_validator(mode="after")
    def validate_session_start_before_charging_start(cls, values):
        charging_start = values.charging_start
        session_start = values.session_start
        if session_start is not None and charging_start is not None:
            if session_start > charging_start:
                raise ValueError("SessionStart cannot be after ChargingStart")
        return values


class ChargingEndValidatorMixin:
    @model_validator(mode="after")
    @classmethod
    def validate_charging_end(cls, values):
        charging_start = values.charging_start
        charging_end = values.charging_end
        session_start = values.session_start

        if charging_end is not None:
            if charging_end > datetime.now(pytz.utc):
                raise ValueError("ChargingEnd cannot be in the future")
        if charging_start is not None and charging_end is not None:
            if charging_start > charging_end:
                raise ValueError("ChargingStart cannot be after ChargingEnd")
        if session_start is not None and charging_end is not None:
            if session_start > charging_end:
                raise ValueError("SessionStart cannot be after ChargingEnd")
        return values


class SessionEndValidatorMixin:
    @model_validator(mode="after")
    @classmethod
    def validate_session_end(cls, values):
        charging_end = values.charging_end
        session_start = values.session_start
        session_end = values.session_end
        if session_end is not None:
            if session_end > datetime.now(pytz.utc):
                raise ValueError("SessionEnd cannot be in the future")
        if session_start is not None and session_end is not None:
            if session_start > session_end:
                raise ValueError("SessionStart cannot be after SessionEnd")
        if charging_end is not None and session_end is not None:
            if charging_end > session_end:
                raise ValueError("ChargingEnd cannot be after SessionEnd")
        return values


class MeterValueEndValidatorMixin:
    @model_validator(mode="after")
    @classmethod
    def validate_meter_value_end(cls, values):
        meter_value_start = values.meter_value_start
        meter_value_end = values.meter_value_end
        meter_value_in_between = values.meter_value_in_between

        if meter_value_start and meter_value_start > meter_value_end:
            raise ValueError("MeterValueStart cannot be after MeterValueEnd")
        if meter_value_in_between:
            for mv in meter_value_in_between.meterValues:
                if mv > meter_value_end:
                    raise ValueError(
                        "MeterValueInBetween cannot be after MeterValueEnd"
                    )
        return values
