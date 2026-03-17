from datetime import datetime, timezone as dt_timezone
from typing import Annotated, List, Optional

from ninja import Schema
from pydantic import ConfigDict, Field, StringConstraints, model_validator, HttpUrl

from ocpi22.cpo.schemas import GeoLocation, validate_country

class TerminalIn(Schema):

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    terminal_id: Annotated[str, StringConstraints(min_length=1, max_length=36)]
    customer_reference: Optional[Annotated[str, StringConstraints(min_length=1, max_length=36)]] = None
    party_id: Optional[Annotated[str, StringConstraints(min_length=3, max_length=3)]] = None
    invoice_base_url: Optional[HttpUrl] = None
    location_ids: List[Annotated[str, StringConstraints(min_length=1, max_length=36)]] = Field(default_factory=list)
    evse_uids: List[Annotated[str, StringConstraints(min_length=1, max_length=36)]] = Field(default_factory=list)
    last_updated: datetime = Field(default_factory=lambda: datetime.now(dt_timezone.utc))

    @model_validator(mode="after")
    def validate_location(self) -> "TerminalIn":
        if not self.location_ids and not self.evse_uids:
            raise ValueError("Either location_ids or evse_uids must be provided.")

        if self.country:
            validate_country(self.country)

        return self


class TerminalOut(Schema):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    terminal_id: str
    customer_reference: Optional[str] = None
    party_id: Optional[str] = None
    country_code: Optional[str] = None

    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    coordinates: Optional[GeoLocation] = None

    invoice_base_url: Optional[str] = None
    invoice_creator: Optional[str] = None

    location_ids: List[str] = Field(default_factory=list)
    evse_uids: List[str] = Field(default_factory=list)

    last_updated: datetime
