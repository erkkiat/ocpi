from dataclasses import dataclass

from ocpi22.choices import OcpiModuleEnum
from ocpiconnector.ocpi_identities import Party


@dataclass(eq=True, frozen=True)
class OCPIUrlComponents:
    path: str
    module: OcpiModuleEnum
    parameters: str


@dataclass(eq=True, frozen=True)
class AdhocToken:
    valid: bool
    owner: Party
    uid: str
    type: str

    def party(self):
        return str(self.owner)

    def __str__(self):
        return f'{self.party()}: {self.type} {self.uid}'

    def get(self, key, default=None):
        return getattr(self, key, default)
