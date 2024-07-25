from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class MeterValuesSchema(BaseModel):
    session_id: str
    kwh: float
    soc: float
    power: int
    datestamp: Optional[datetime] = None


class StartSchema(BaseModel):
    evse_uid: str
    connector_id: str
    token_id: str
    internal_reference: Optional[str] = None
    start_kwh: Optional[float] = None


class StopSchema(BaseModel):
    session_id: str
    internal_reference: Optional[str] = None
    stop_kwh: Optional[float] = None
    stop_timestamp: Optional[datetime] = None
