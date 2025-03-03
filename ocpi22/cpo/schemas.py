from zoneinfo import ZoneInfo

from django.conf import settings
from ninja import Schema, Field
from typing import List, Optional
from datetime import datetime

from pydantic import constr, field_validator, conint

from ocpi22 import choices
from ocpi22.choices import OCPICapabilityEnum
from ocpi22.ocpi.util import Ocpi
import generic.countries


class OpeningTimes(Schema): ...


class GeoLocation(Schema):
    latitude: constr(pattern=r"^-?\d{1,2}\.\d+$")
    longitude: constr(pattern=r"^-?\d{1,2}\.\d+$")


class Connector(Schema):
    uid: constr(min_length=1, max_length=settings.OCPI_22_MAX_UID_LENGTH) = Field(
        ..., alias="id"
    )
    standard: str
    format: str
    power_type: str
    max_voltage: conint(gt=0)
    max_amperage: conint(gt=0)
    max_electric_power: conint(gt=0)
    tariff_ids: Optional[List[str]] = None
    last_updated: datetime

    @field_validator("standard")
    def validate_standard(cls, value):
        if not any(Ocpi.STANDARD_CHOICES_LIST):
            raise ValueError(f"{value} is not a valid standard")
        return value

    @field_validator("format")
    def validate_format(cls, value):
        if not any(Ocpi.FORMAT_CHOICES_LIST):
            raise ValueError(f"{value} is not a valid format")
        return value

    @field_validator("power_type")
    def validate_power_type(cls, value):
        if not any(Ocpi.POWERTYPE_CHOICES_221_LIST):
            raise ValueError(f"{value} is not a valid power_type")
        return value


class EVSE(Schema):
    uid: constr(min_length=1, max_length=settings.OCPI_22_MAX_UID_LENGTH)
    evse_id: constr(min_length=7, max_length=48)
    status: str
    last_updated: datetime
    connectors: List[Connector] = Field(
        ..., description="List of connectors for this EVSE"
    )
    capabilities: Optional[OCPICapabilityEnum] = None

    @field_validator("status")
    def validate_status(cls, value):
        if not any(choices.EVSE_STATUS_CHOICES_LIST):
            raise ValueError(f"{value} is not a valid status")
        return value


class LocationIn(Schema):
    country_code: constr(min_length=2, max_length=2) = Field(...)
    party_id: constr(min_length=3, max_length=3) = Field(...)
    uid: constr(min_length=1, max_length=settings.OCPI_22_MAX_UID_LENGTH) = Field(...)
    publish: bool
    address: constr(max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH) = Field(...)
    city: constr(max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH)
    postal_code: constr(max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH)
    state: constr(max_length=20)
    country: str
    coordinates: GeoLocation = Field(..., description="Geographical coordinates")
    evses: List[EVSE] = Field(
        ..., description="List of EVSEs available at this location"
    )
    time_zone: str
    opening_times: Optional[List[OpeningTimes]]
    parking_type: Optional[str] = None
    facilities: Optional[OCPICapabilityEnum] = None
    time_zone: Optional[str] = None
    charging_when_closed: Optional[bool] = False
    last_updated: datetime

    @field_validator("country")
    def validate_country(cls, value):
        if not any(code == value for code, name in generic.countries.COUNTRIES_ISO_3):
            raise ValueError(f"{value} is not a valid country")
        return value

    @field_validator("parking_type")
    def validate_parking_type(cls, value):
        if not any(code == value for code, name in choices.PARKING_CHOICES):
            raise ValueError(f"{value} is not a valid parking type")
        return value

    @field_validator("time_zone")
    def validate_time_zone(cls, value):
        try:
            ZoneInfo(value)
        except Exception:
            raise ValueError(f"{value} is not a valid time zone")
        return value
