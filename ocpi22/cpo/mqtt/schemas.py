from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, RootModel

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


@dataclass
class CachedSession:
    session_id: str
    kwh: float
    timestamp: datetime
    route_to_msp: Route
