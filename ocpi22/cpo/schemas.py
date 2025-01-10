from enum import Enum

from pydantic import Field
from pydantic.v1 import BaseModel, validator

from ocpi22.util import CURRENCY_CHOICES


class SolidPriceComponent(Enum):
    KWH = "KILOWATT_HOUR"
    MINUTE = "MINUTE"
    HOUR = "HOUR"


class SolidDefaultTariff(BaseModel):
    currency: str = Field(
        default="EUR",
        description="The default currency of the tariff",
        examples=["USD"],
    )
    price: float = Field(
        default=..., description="The default price of the tariff", examples=[0.1]
    )
    price_component: SolidPriceComponent = Field(
        default=SolidPriceComponent.KWH,
        description="The default price component of the tariff",
        examples=["KILOWATT_HOUR", "MINUTE", "HOUR"],
    )

    @classmethod
    @validator("currency")
    def check_currency(cls, value):
        valid_currencies = {code for code, _ in CURRENCY_CHOICES}
        if value not in valid_currencies:
            raise ValueError(
                f"Invalid currency: {value}. Must be one of {valid_currencies}."
            )
        return value

    @classmethod
    def get_price_component(cls, price_component: str) -> SolidPriceComponent:
        match price_component:
            case "KILOWATT_HOUR":
                return SolidPriceComponent.KWH
            case "MINUTE":
                return SolidPriceComponent.MINUTE
            case "HOUR":
                return SolidPriceComponent.HOUR
            case _:
                raise ValueError("Invalid price_component")
