from datetime import datetime
from typing import Optional, List

from ninja import Schema
from pydantic import Field


class GeoLocationSchema(Schema):
    latitude: str = Field(max_length=10)
    longitude: str = Field(max_length=11)


class TerminalIn(Schema):
    terminal_id: str = Field(..., max_length=36)
    customer_reference: Optional[str] = Field(None, max_length=36)
    invoice_base_url: Optional[str] = None

    location_uids: List[str] = Field(default_factory=list)
    evse_uids: List[str] = Field(default_factory=list)

    last_updated: Optional[datetime] = Field(default=None)


class TerminalOut(Schema):
    terminal_id: str
    customer_reference: Optional[str] = None
    party_id: Optional[str] = None
    country_code: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    coordinates: Optional[GeoLocationSchema] = None
    invoice_base_url: Optional[str] = None
    invoice_creator: Optional[str] = None

    location_ids: List[str] = Field(default_factory=list)
    evse_uids: List[str] = Field(default_factory=list)

    last_updated: datetime
