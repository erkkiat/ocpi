from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, RootModel

from ocpi22.choices import OcppStatusChoices
from ocpi22.routing import Route


class Uid(RootModel):
    root: str = Field(..., max_length=36)


class MeterValues(BaseModel):
    session_id: Optional[str] = Field(..., max_length=36, description="The unique identifier of the session.")
    internal_reference: Optional[str] = Field(None, description="Optional internal reference for the Session.")
    kwh: float = Field(..., description="The metered energy in kWh.")
    soc: Optional[float] = Field(None, description="The state of charge in percentage.")
    power: Optional[float] = Field(None, description="The power in kW.")
    timestamp: str = Field(..., description="The timestamp of the meter value.")


class EvseStatus(str, Enum):
    AVAILABLE = OcppStatusChoices.AVAILABLE.value
    PREPARING = OcppStatusChoices.PREPARING.value
    CHARGING = OcppStatusChoices.CHARGING.value
    SUSPENDEDEV = OcppStatusChoices.SUSPENDEDEV.value
    SUSPENDEDEVSE = OcppStatusChoices.SUSPENDEDEVSE.value
    FINISHING = OcppStatusChoices.FINISHING.value
    RESERVED = OcppStatusChoices.RESERVED.value
    UNAVAILABLE = OcppStatusChoices.UNAVAILABLE.value
    FAULTED = OcppStatusChoices.FAULTED.value


class EvseStatusUpdate(BaseModel):
    evse_uid: str
    status: EvseStatus
    timestamp: Optional[str] = Field(None, description="The optional, but recommended timestamp of the status change.")

    class Config:
        json_encoders = {
            EvseStatus: lambda v: v.value,  # Convert Enum to its value
        }

@dataclass
class CachedSession:
    session_id: str
    kwh: float
    timestamp: datetime
    route_to_msp: Route
