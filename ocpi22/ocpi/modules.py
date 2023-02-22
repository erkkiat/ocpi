from functools import lru_cache

from ocpi22.choices import OcpiModuleEnum

ocpi_modules = [x.value for x in OcpiModuleEnum]


@lru_cache(maxsize=0)
def get_module_urls() -> list:
    from util import reverse
    return (reverse(name) for name in ('location-list', 'commands-list', 'token-list'))
