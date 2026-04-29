from datetime import datetime
from typing import Annotated, List, Optional

from ninja import Schema
from pydantic import ConfigDict, Field, StringConstraints, model_validator, HttpUrl

from ocpi22.cpo.schemas import GeoLocation


class TerminalIn(Schema):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    location_ids: List[
        Annotated[str, StringConstraints(min_length=1, max_length=36)]
    ] = Field(default_factory=list)
    evse_uids: List[Annotated[str, StringConstraints(min_length=1, max_length=36)]] = (
        Field(default_factory=list)
    )
    invoice_base_url: Optional[HttpUrl] = None


class TerminalPutIn(TerminalIn):
    @model_validator(mode="after")
    def validate_location(self) -> "TerminalPutIn":
        if not self.location_ids and not self.evse_uids:
            raise ValueError("Either location_ids or evse_uids must be provided.")
        return self


class TerminalOut(Schema):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    terminal_id: Annotated[str, StringConstraints(min_length=1, max_length=36)]
    customer_reference: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=36)]
    ] = None
    party_id: Optional[
        Annotated[str, StringConstraints(min_length=3, max_length=3)]
    ] = None
    country_code: Optional[
        Annotated[str, StringConstraints(min_length=2, max_length=2)]
    ] = None
    address: Optional[Annotated[str, StringConstraints(max_length=45)]] = None
    city: Optional[Annotated[str, StringConstraints(max_length=45)]] = None
    postal_code: Optional[Annotated[str, StringConstraints(max_length=10)]] = None
    state: Optional[Annotated[str, StringConstraints(max_length=20)]] = None
    country: Optional[Annotated[str, StringConstraints(min_length=3, max_length=3)]] = (
        None
    )
    coordinates: Optional[GeoLocation] = None
    location_ids: List[str] = Field(default_factory=list)
    evse_uids: List[str] = Field(default_factory=list)
    last_updated: datetime
    name: Optional[str] = None
    invoice_base_url: Optional[str] = None
    invoice_creator: Optional[str] = None
