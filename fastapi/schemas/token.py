from datetime import datetime, timedelta
from enum import Enum
from typing import List

from django.conf import settings
from pydantic import BaseModel, Field


class TokenAllowedEnum(str, Enum):
    """
    Allowed values for the token authorization/status.
    """

    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    NO_CREDIT = "NO_CREDIT"
    NOT_ALLOWED = "NOT_ALLOWED"


class TokenSchema(BaseModel):
    id: str = Field(..., alias="id", max_length=settings.OCPI_22_MAX_UID_LENGTH)
    allowed: TokenAllowedEnum
    language: str = Field(default="en_gb", max_length=5)
    next_update: datetime = Field(
        default_factory=lambda: datetime.utcnow() + timedelta(hours=24)
    )


class TokenListSchema(BaseModel):
    tokens: List[TokenSchema]
