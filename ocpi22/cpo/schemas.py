from zoneinfo import ZoneInfo

from django.conf import settings
from ninja import Schema, Field
from typing import List, Optional
from datetime import datetime

from pydantic import constr, field_validator, conint

from generic import countries
from ocpi22.choices import (
    OCPICapabilityEnum,
    OCPIFacilityEnum,
    EVSEStatusEnum,
    ParkingChoicesEnum,
)
from ocpi22.ocpi.util import Ocpi


class RegularHours(Schema):
    weekday: int
    period_begin: constr(min_length=5, max_length=5)
    period_end: constr(min_length=5, max_length=5)


class ExceptionalPeriod(Schema):
    period_begin: datetime
    period_end: datetime


class OpeningTimes(Schema):
    regular_hours: Optional[List[RegularHours]]
    twentyfourseven: bool
    exceptional_openings: Optional[List[ExceptionalPeriod]] = None
    exceptional_closings: Optional[List[ExceptionalPeriod]] = None


class GeoLocation(Schema):
    latitude: constr(pattern=r"^-?\d{1,2}\.\d+$")
    longitude: constr(pattern=r"^-?\d{1,2}\.\d+$")


class Connector(Schema):
    uid: constr(min_length=1, max_length=settings.OCPI_22_MAX_UID_LENGTH) = Field(
        ..., alias="id"
    )
    standard: Ocpi.StandardChoicesEnum
    format: Ocpi.FormatChoicesEnum
    power_type: Ocpi.PowerTypeEnum
    max_voltage: conint(gt=0)
    max_amperage: conint(gt=0)
    max_electric_power: Optional[conint(gt=0)] = None
    tariff_ids: Optional[List[str]] = None
    last_updated: datetime


class EVSE(Schema):
    uid: constr(min_length=1, max_length=settings.OCPI_22_MAX_UID_LENGTH)
    evse_id: constr(min_length=7, max_length=48)
    status: EVSEStatusEnum
    last_updated: datetime
    connectors: List[Connector] = Field(
        ..., description="List of connectors for this EVSE"
    )
    capabilities: Optional[List[OCPICapabilityEnum]] = None


class LocationIn(Schema):
    country_code: constr(min_length=2, max_length=2) = Field(...)
    party_id: constr(min_length=3, max_length=3) = Field(...)
    uid: constr(min_length=1, max_length=settings.OCPI_22_MAX_UID_LENGTH) = Field(
        ..., alias="id"
    )
    publish: bool
    address: constr(max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH) = Field(...)
    city: constr(max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH)
    postal_code: constr(max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH)
    state: Optional[constr(max_length=20)] = None
    country: str
    coordinates: GeoLocation = Field(..., description="Geographical coordinates")
    evses: List[EVSE] = Field(
        ..., description="List of EVSEs available at this location"
    )
    time_zone: str
    opening_times: Optional[OpeningTimes] = None
    parking_type: Optional[ParkingChoicesEnum] = None
    facilities: Optional[List[OCPIFacilityEnum]] = None
    time_zone: Optional[str] = None
    charging_when_closed: Optional[bool] = False
    last_updated: datetime

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
