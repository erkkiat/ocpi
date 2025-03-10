from zoneinfo import ZoneInfo

from django.conf import settings
from ninja import Schema, Field
from typing import List, Optional
from datetime import datetime

from pydantic import field_validator, ConfigDict, NonNegativeInt, StringConstraints
from typing_extensions import Annotated

from generic import countries
from ocpi22.choices import (
    OCPICapabilityEnum,
    OCPIFacilityEnum,
    EVSEStatusEnum,
    ParkingChoicesEnum,
)
from ocpi22.ocpi.util import Ocpi


class BaseConfig(Schema):
    model_config = ConfigDict(extra="forbid")


class OCPIImage(BaseConfig):
    url: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    thumbnail: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    category: Annotated[str, StringConstraints(min_length=1, max_length=20)]
    type: Annotated[str, StringConstraints(min_length=1, max_length=20)]
    width: NonNegativeInt
    height: NonNegativeInt


class BusinessDetails(BaseConfig):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    website: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    logo: Optional[Annotated[str, StringConstraints(min_length=1, max_length=20)]] = (
        None
    )


class RegularHours(BaseConfig):
    weekday: Annotated[int, Field(ge=1, le=7)]
    period_begin: Annotated[str, StringConstraints(min_length=5, max_length=5)]
    period_end: Annotated[str, StringConstraints(min_length=5, max_length=5)]


class ExceptionalPeriod(BaseConfig):
    period_begin: datetime
    period_end: datetime


class OpeningTimes(BaseConfig):
    regular_hours: Optional[List[RegularHours]]
    twentyfourseven: bool
    exceptional_openings: Optional[List[ExceptionalPeriod]] = None
    exceptional_closings: Optional[List[ExceptionalPeriod]] = None


class GeoLocation(BaseConfig):
    latitude: Annotated[str, StringConstraints(pattern=r"^-?\d{1,2}\.\d+$")]
    longitude: Annotated[str, StringConstraints(pattern=r"^-?\d{1,2}\.\d+$")]


class Connector(BaseConfig):
    uid: Annotated[
        str, StringConstraints(min_length=1, max_length=settings.OCPI_22_MAX_UID_LENGTH)
    ] = Field(..., alias="id")
    standard: Ocpi.StandardChoicesEnum
    format: Ocpi.FormatChoicesEnum
    power_type: Ocpi.PowerTypeEnum
    max_voltage: NonNegativeInt
    max_amperage: NonNegativeInt
    max_electric_power: Optional[NonNegativeInt] = None
    tariff_ids: Optional[List[str]] = None
    last_updated: datetime
    terms_and_conditions: Optional[str] = None


class EVSE(BaseConfig):
    uid: Annotated[
        str, StringConstraints(min_length=1, max_length=settings.OCPI_22_MAX_UID_LENGTH)
    ]
    evse_id: Annotated[str, StringConstraints(min_length=7, max_length=48)]
    status: EVSEStatusEnum
    last_updated: datetime
    connectors: List[Connector] = Field(
        ..., description="List of connectors for this EVSE"
    )
    capabilities: Optional[List[OCPICapabilityEnum]] = None


class LocationIn(BaseConfig):
    country_code: Annotated[str, StringConstraints(min_length=2, max_length=2)] = Field(
        ...
    )
    party_id: Annotated[str, StringConstraints(min_length=3, max_length=3)] = Field(...)
    uid: Annotated[
        str, StringConstraints(min_length=1, max_length=settings.OCPI_22_MAX_UID_LENGTH)
    ] = Field(..., alias="id")
    publish: bool
    name: Optional[Annotated[str, StringConstraints(min_length=1)]] = None
    address: Annotated[
        str, StringConstraints(max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH)
    ] = Field(...)
    city: Annotated[
        str, StringConstraints(max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH)
    ]
    postal_code: Annotated[
        str, StringConstraints(max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH)
    ]
    state: Optional[Annotated[str, StringConstraints(max_length=20)]] = None
    country: str
    coordinates: GeoLocation = Field(..., description="Geographical coordinates")
    evses: List[EVSE] = Field(
        ..., description="List of EVSEs available at this location"
    )
    opening_times: Optional[OpeningTimes] = None
    parking_type: Optional[ParkingChoicesEnum] = None
    facilities: Optional[List[OCPIFacilityEnum]] = None
    time_zone: Optional[str] = None
    charging_when_closed: Optional[bool] = False
    last_updated: datetime
    operator: Optional[BusinessDetails] = None
    suboperator: Optional[BusinessDetails] = None
    owner: Optional[BusinessDetails] = None

    @field_validator("country")
    def validate_country(cls, value):
        if value not in countries.COUNTRIES_ISO_3_SET:
            raise ValueError(f"{value} is not a valid country")
        return value

    @field_validator("time_zone")
    def validate_time_zone(cls, value):
        try:
            ZoneInfo(value)
        except Exception:
            raise ValueError(f"{value} is not a valid time zone")
        return value
