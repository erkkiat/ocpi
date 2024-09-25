from functools import lru_cache
from typing import Generator

from ocpi22.choices import OcpiModuleEnum

ocpi_modules = [x.value for x in OcpiModuleEnum]


@lru_cache(maxsize=0)
def get_module_urls() -> Generator:
    from util import reverse

    return (
        reverse(name)
        for name in (
            "location-list",
            "commands-list",
            "token-list",
            "session-list",
            "cdr-list",
        )
    )
