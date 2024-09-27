from typing import List, Any

from integrations.hubject.schemas import ERoamingPushEvseData
from ocpi22.models.location import Location


class OCPIToOICPConverter:
    def __init__(self, oicp_version: str, ocpi_version: str, data: List[Any]):
        self.oicp_version = oicp_version
        self.ocpi_version = ocpi_version
        self.data = data

    def _convert_location(self, location: Location) -> ERoamingPushEvseData: ...

    def _convert_evse(self, evses: List[Location]) -> List[ERoamingPushEvseData]: ...

    def convert(self): ...

    def construct_ocpi_format(self) -> List[ERoamingPushEvseData]: ...
