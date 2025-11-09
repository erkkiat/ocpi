from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, RootModel

from ocpi22.choices import OcppStatusChoices, AuthorizationEnum
from ocpi22.routing import Route


class Uid(RootModel):
    root: str = Field(..., max_length=36)


class MeterValues(BaseModel):
    session_id: Optional[str] = Field(
        ..., max_length=36, description="The unique identifier of the session."
    )
    kwh: float = Field(..., description="The metered energy in kWh.")
    soc: Optional[float] = Field(None, description="The state of charge in percentage.")
    power: Optional[float] = Field(None, description="The power in kW.")
    timestamp: datetime = Field(..., description="The timestamp of the meter value.")


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

    class Config:
        json_encoders = {
            EvseStatus: lambda v: v.value,  # Convert Enum to its value
        }


class TokenAuthorizationMessageIn(BaseModel):
    token_id: str
    evse_id: str
    correlation_id: str


class TokenAuthorizationResponse(BaseModel):
    allowed: AuthorizationEnum
    session_id: str | None = None
    correlation_id: str

    class Config:
        use_enum_values = True


@dataclass
class CachedSession:
    session_id: str
    kwh: float
    timestamp: datetime
    route_to_msp: Route
    meter_value_update_date_time: Optional[datetime] = None
