from functools import lru_cache

from ocpi22.choices import OcpiModuleEnum
from ocpi22.ocpi.modules import ocpi_modules, get_module_urls
from ocpi22.ocpi.dataclasses import OCPIUrlComponents


@lru_cache(maxsize=100)
def parse_ocpi_url(url: str) -> OCPIUrlComponents:
    """
    >>> parse_ocpi_url('/ocpi//2.2.1/commands/START_SESSION?a=1')
    OCPIUrlComponents(path='/ocpi//2.2.1/commands', module=<OcpiModuleEnum.COMMANDS: 'commands'>, parameters='START_SESSION?a=1')
    >>> parse_ocpi_url('/ocpi//2.2.1/commands/START_SESSION/')
    OCPIUrlComponents(path='/ocpi//2.2.1/commands', module=<OcpiModuleEnum.COMMANDS: 'commands'>, parameters='START_SESSION')
    >>> parse_ocpi_url('/ocpi//2.2.1/tokens/EKI1/authorize')
    OCPIUrlComponents(path='/ocpi//2.2.1/tokens', module=<OcpiModuleEnum.TOKENS: 'tokens'>, parameters='EKI1/authorize')
    >>> parse_ocpi_url('/ocpi//2.2.1/locations?limit=5')
    OCPIUrlComponents(path='/ocpi//2.2.1/locations', module=<OcpiModuleEnum.LOCATIONS: 'locations'>, parameters='?limit=5')
    >>> parse_ocpi_url('/ocpi/2.2.1/sessions/FI/000/FI*000*S*54FED8A974E942A4BC82165D867')
    OCPIUrlComponents(path='/ocpi/2.2.1/sessions', module=<OcpiModuleEnum.SESSIONS: 'sessions'>, parameters='')
    """
    url = url.rstrip('/')
    path = ''
    module = ''
    parameters = ''

    # Figure out the OCPI module
    for m in ocpi_modules:
        if m in url:
            module = m
            break

    # Find the OCPI module path part and separate URL parameters (of course query, but also possible OCPI Command)
    for module_url in get_module_urls():
        if module_url in url:
            path = module_url
            parameters = url.replace(module_url, '').strip('/')
            break

    return OCPIUrlComponents(path, OcpiModuleEnum(module), parameters)
