from zoneinfo import ZoneInfo

from django.conf import settings
from ninja import Schema, Field
from typing import List, Optional
from datetime import datetime, timezone

from pydantic import (
    ConfigDict,
    NonNegativeInt,
    StringConstraints,
    AfterValidator,
    model_validator,
)
from pydantic_extra_types.coordinate import Latitude, Longitude
from pydantic_extra_types.phone_numbers import PhoneNumber
from typing_extensions import Annotated

from generic import countries
from integrations.hubject.schemas import (
    CalibrationLawDataAvailability,
    Accessibility,
)
from ocpi22.choices import (
    OCPICapability,
    OCPIFacility,
    EVSEStatus,
    ParkingChoices,
    ParkingRestriction,
    EnvironmentalImpactCategory,
    EnergySourceCategory,
    TokenType,
)
from ocpi22.ocpi.util import Ocpi


class BaseSchema(Schema):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class StatusSchedule(BaseSchema):
    period_begin: datetime
    period_end: datetime
    status: EVSEStatus


class DisplayText(BaseSchema):
    language: Annotated[str, StringConstraints(min_length=2, max_length=2)]
    text: Annotated[str, StringConstraints(min_length=1, max_length=512)]


class PublishTokenType(BaseSchema):
    uid: Optional[Annotated[str, StringConstraints(max_length=36)]] = None
    type: Optional[TokenType] = None
    visual_number: Optional[Annotated[str, StringConstraints(max_length=64)]] = None
    issuer: Optional[Annotated[str, StringConstraints(max_length=64)]] = None
    group_id: Optional[Annotated[str, StringConstraints(max_length=36)]] = None


class AdditionalGeoLocation(BaseSchema):
    latitude: Latitude
    longitude: Longitude
    name: Optional[DisplayText] = None


class EnvironmentalImpact(BaseSchema):
    category: EnvironmentalImpactCategory
    amount: Annotated[float, Field(...)]


class EnergySource(BaseSchema):
    source: EnergySourceCategory
    percentage: Annotated[float, Field(..., ge=0, le=100)]


class EnergyMix(BaseSchema):
    is_green_energy: Annotated[bool, Field(...)]
    energy_sources: Annotated[List[EnergySource], Field(...)]
    environ_impact: Annotated[List[EnvironmentalImpact], Field(...)]
    supplier_name: Annotated[Optional[str], Field(None, max_length=64)]
    energy_product_name: Annotated[Optional[str], Field(None, max_length=64)]


class OCPIImage(BaseSchema):
    url: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    thumbnail: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    category: Annotated[str, StringConstraints(min_length=1, max_length=20)]
    type: Annotated[str, StringConstraints(min_length=1, max_length=20)]
    width: NonNegativeInt
    height: NonNegativeInt


class BusinessDetails(BaseSchema):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    website: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    logo: Optional[Annotated[str, StringConstraints(min_length=1, max_length=20)]] = (
        None
    )


class RegularHours(BaseSchema):
    weekday: Annotated[int, Field(ge=1, le=7)]
    period_begin: Annotated[str, StringConstraints(min_length=5, max_length=5)]
    period_end: Annotated[str, StringConstraints(min_length=5, max_length=5)]


class ExceptionalPeriod(BaseSchema):
    period_begin: datetime
    period_end: datetime


class OpeningTimes(BaseSchema):
    regular_hours: Optional[List[RegularHours]] = None
    twentyfourseven: bool
    exceptional_openings: Optional[List[ExceptionalPeriod]] = None
    exceptional_closings: Optional[List[ExceptionalPeriod]] = None

    @model_validator(mode="after")
    def validate_hours(self):
        if not self.twentyfourseven and not self.regular_hours:
            raise ValueError("regular_hours is required when twentyfourseven is False")

        return self


class GeoLocation(BaseSchema):
    latitude: Latitude
    longitude: Longitude


class SolidConnector(BaseSchema):
    uid: Annotated[
        str, StringConstraints(min_length=1, max_length=settings.OCPI_22_MAX_UID_LENGTH)
    ] = Field(..., alias="id")
    standard: Ocpi.Standard
    format: Ocpi.Format
    power_type: Ocpi.PowerType
    max_voltage: NonNegativeInt
    max_amperage: NonNegativeInt
    max_electric_power: Optional[NonNegativeInt] = None
    tariff_ids: Optional[List[str]] = None
    last_updated: datetime
    terms_and_conditions: Optional[str] = None


class SolidEvse(BaseSchema):
    uid: Annotated[
        str, StringConstraints(min_length=1, max_length=settings.OCPI_22_MAX_UID_LENGTH)
    ]
    evse_id: Optional[
        Annotated[str, StringConstraints(min_length=7, max_length=48)]
    ] = None
    status: EVSEStatus
    status_schedule: Optional[List[StatusSchedule]] = None
    capabilities: Optional[List[OCPICapability]] = None
    connectors: List[SolidConnector] = Field(
        ..., description="List of connectors for this EVSE"
    )
    floor_level: Optional[Annotated[str, StringConstraints(max_length=4)]] = None
    coordinates: Optional[GeoLocation] = None
    physical_reference: Optional[Annotated[str, StringConstraints(max_length=16)]] = (
        None
    )
    directions: Optional[List[DisplayText]] = None
    parking_restrictions: Optional[List[ParkingRestriction]] = None
    images: Optional[List[OCPIImage]] = None
    last_updated: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when this Evse was last updated",
    )
    is_dynamic_info_available: Optional[bool] = Field(
        False,
        description="Indicates whether dynamic information is available from this EVSE.",
    )


def validate_country(value):
    if value not in countries.COUNTRIES_ISO_3_SET:
        raise ValueError(f"{value} is not a valid country")
    return value


def validate_time_zone(value):
    try:
        ZoneInfo(value)
    except Exception:
        raise ValueError(f"{value} is not a valid time zone")
    return value


class SolidLocation(BaseSchema):
    country_code: Annotated[str, StringConstraints(min_length=2, max_length=2)] = Field(
        ...
    )
    party_id: Annotated[str, StringConstraints(min_length=3, max_length=3)] = Field(...)
    uid: Annotated[
        str, StringConstraints(min_length=1, max_length=settings.OCPI_22_MAX_UID_LENGTH)
    ] = Field(..., alias="id")
    publish: bool
    publish_allowed_to: Optional[List[PublishTokenType]] = None
    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    address: Annotated[
        str, StringConstraints(max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH)
    ] = Field(...)
    city: Annotated[
        str, StringConstraints(max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH)
    ]
    postal_code: Optional[
        Annotated[
            str, StringConstraints(max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH)
        ]
    ] = None
    state: Optional[Annotated[str, StringConstraints(max_length=20)]] = None
    country: Annotated[str, AfterValidator(validate_country)]
    coordinates: GeoLocation = Field(..., description="Geographical coordinates")
    related_locations: Optional[List[AdditionalGeoLocation]] = None
    parking_type: Optional[ParkingChoices] = None
    evses: Optional[List[SolidEvse]] = Field(
        None, description="List of EVSEs available at this location"
    )
    directions: Optional[List[DisplayText]] = None
    operator: Optional[BusinessDetails] = None
    suboperator: Optional[BusinessDetails] = None
    owner: Optional[BusinessDetails] = None
    facilities: Optional[List[OCPIFacility]] = None
    time_zone: Annotated[str, AfterValidator(validate_time_zone)]
    opening_times: Optional[OpeningTimes] = None
    charging_when_closed: Optional[bool] = False
    images: Optional[List[OCPIImage]] = None
    energy_mix: Optional[List[EnergyMix]] = None
    last_updated: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when this Location was last updated",
    )
    roaming_enabled: Optional[bool] = Field(
        True,
        description="Indicates whether to share the location with roaming partners",
    )
    is_green_energy: Optional[bool] = Field(
        False,
        description="Indicates whether the location only uses renewable energy sources.",
    )
    calibration_law_data_availability: Optional[CalibrationLawDataAvailability] = Field(
        CalibrationLawDataAvailability.Local
    )
    # payment_options: Optional[List[PaymentOption]] = Field(
    #     None, description="List of payment options available at this location."
    # )
    accessibility: Optional[List[Accessibility]] = Field(
        None, description="Specifies how the charging station can be accessed."
    )
    hotline_phone_number: Optional[PhoneNumber] = None
    is_hubject_compatible: Optional[bool] = Field(
        False, description="Indicates whether the location is compatible with Hubject."
    )


class Error(Schema):
    message: str


class StatusScheduleOut(BaseSchema):
    period_begin: datetime
    period_end: datetime
    status: str


class ConnectorOut(Connector):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, use_enum_values=True
    )


class EVSEOut(EVSE):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, use_enum_values=True
    )

    status_schedule: Optional[List[StatusScheduleOut]] = None
    connectors: List[ConnectorOut] = Field(
        ..., description="List of connectors for this EVSE"
    )


class LocationOut(LocationIn):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, use_enum_values=True
    )

    evses: List[EVSEOut] = Field(
        ..., description="List of EVSEs available at this location"
    )
