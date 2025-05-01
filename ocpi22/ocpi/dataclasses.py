from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ocpi22.choices import OcpiModuleEnum
from ocpiconnector.party import Party


@dataclass(eq=True, frozen=True)
class OCPIUrlComponents:
    path: str
    module: OcpiModuleEnum
    parameters: str


@dataclass(eq=True, frozen=True)
class AdhocToken:
    billed_to: Party
    uid: str
    type: str
    ocpi_master: Any  # "Any" to avoid importing CredentialsRole

    # Optional fields
    valid: bool = field(default=True)
    country_code: str = field(default="")
    party_id: str = field(default="")
    whitelist: str = field(default="NEVER")
    visual_number: str = field(default="")
    issuer: str = field(default="")
    group_id: str = field(default="")
    language: str = field(default="en")
    default_profile_type: str = field(default="REGULAR")
    energy_contract: str = field(default="")
    contract_id: str = field(default="-")
    last_updated: datetime = field(default=None)

    def party_str(self):
        return str(self.billed_to)

    def get_party(self):
        return self.billed_to

    def __str__(self):
        return f"{self.party_str()}: {self.type} {self.uid}"

    def get(self, key, default=None):
        return getattr(self, key, default)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)
