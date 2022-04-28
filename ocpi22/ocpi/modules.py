from functools import lru_cache

from rest_framework.reverse import reverse

from ocpi22.choices import OcpiModuleEnum

ocpi_modules = [x.value for x in OcpiModuleEnum]


@lru_cache(maxsize=0)
def get_module_urls() -> list:
    return (reverse(name) for name in ('location-list', 'commands-list', 'token-list'))
