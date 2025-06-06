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


class TokenAuthorizationRequest(BaseModel):
    request_id: str = Field(
        ..., description="Unique identifier for this authorization request"
    )
    token_uid: str = Field(..., description="Token UID to authorize")
    location_id: Optional[str] = Field(
        None, description="Optional location ID where charging is requested"
    )
    correlation_id: Optional[str] = Field(
        None, description="Optional correlation ID for tracking purposes"
    )


class TokenAuthorizationResponse(BaseModel):
    request_id: str = Field(..., description="The request ID from the original request")
    token_uid: str = Field(..., description="Token UID that was authorized")
    allowed: str = Field(
        ...,
        description="Authorization result: ALLOWED, NOT_ALLOWED, BLOCKED, EXPIRED, NO_CREDIT",
    )
    authorization_reference: Optional[str] = Field(
        None, description="Reference for this authorization"
    )
    responding_party: Optional[str] = Field(
        None, description="Party that provided the authorization"
    )
    status_text: Optional[str] = Field(
        None, description="Human readable status message"
    )
    correlation_id: Optional[str] = Field(
        None, description="Optional correlation ID for tracking purposes"
    )


@dataclass
class CachedSession:
    session_id: str
    kwh: float
    timestamp: datetime
    route_to_msp: Route
