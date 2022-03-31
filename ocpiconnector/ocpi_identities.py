import os
from dataclasses import dataclass
from functools import lru_cache

from icecream import ic

from ocpi22.choices import ROLE_OPTIONS, OcpiRolesEnum


@dataclass(eq=True, frozen=True)
class Party:
    country_code: str
    party_id: str

    def __str__(self):
        return f'{self.country_code}*{self.party_id}'

    def __bool__(self):
        return bool(self.country_code and self.party_id)


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class OCPIIdentities(metaclass=Singleton):
    """
    Store the identities of this OCPI Platform in list and dict form for convenient access

    >>> ocpi_identities['CPO']
    'FI*CPO'
    >>> ocpi_identities.get('EMSP')
    'FI*MSP'
    >>> ocpi_identities.get('AAA')
    '*'
    >>> ocpi_identities.get('AAA', 'BBB')
    'BBB'
    >>> 'FI*CPO' in ocpi_identities
    True
    >>> 'CPO' in ocpi_identities
    True
    >>> 'BBB' in ocpi_identities
    False
    """
    _identities_list = []
    _identities_dict = dict()

    def __init__(self, source: dict = os.environ):
        self._identities_list = list([source.get(i) for i in ROLE_OPTIONS if source.get(i)])
        for n in ROLE_OPTIONS:
            item = source.get(n)
            if item:
                self._identities_dict[n] = item

    def __iter__(self):
        for i in self._identities_list:
            yield i

    def __bool__(self):
        return bool(len(self._identities_list))

    def __contains__(self, item):
        return item in self._identities_list or item in self._identities_dict

    def __sizeof__(self) -> int:
        return len(self._identities_list)

    def __getitem__(self, item) -> str:
        if isinstance(item, str):
            return self._identities_dict[item]
        return self._identities_list[item]

    def __str__(self) -> str:
        return ", ".join(self._identities_list)

    def __repr__(self) -> str:
        return self.__str__()

    def get_dict(self) -> dict:
        return self._identities_dict

    def items(self):
        return self._identities_dict.items()

    def get(self, item, default='*') -> str:
        return self._identities_dict[item] if item in self._identities_dict else default

    @property
    def roles(self):
        return self._identities_dict.keys()


ocpi_identities = OCPIIdentities()


class OCPIPlatform(metaclass=Singleton):
    is_hub = bool('HUB' in ocpi_identities)
    is_cpo = bool('CPO' in ocpi_identities)
    is_emsp = bool('EMSP' in ocpi_identities)


ocpi_platform = OCPIPlatform()


@lru_cache(maxsize=None)
def get_identity(role: str = None, identities=ocpi_identities) -> str:
    """
    >>> get_identity('EMSP')
    'FI*MSP'
    >>> get_identity('CPO')
    'FI*CPO'
    >>> get_identity()
    'FI*CPO'

    @param role:
    @param identities:
    @return:
    """
    if not role:
        return list(identities.items())[0][1]
    return identities.get(role)


@lru_cache(maxsize=None)
def get_our_country_code(role: str = None, identities=ocpi_identities) -> str:
    """
    >>> get_our_country_code('CPO')
    'FI'
    >>> get_our_country_code('EMSP')
    'FI'
    >>> get_our_country_code(None)  # Return the first one (for Credentials DELETE)
    'FI'
    """
    country_code, _party_id = get_identity(role, identities).split('*')
    return country_code


@lru_cache(maxsize=None)
def get_our_party_id(role: str = None, identities=ocpi_identities) -> str:
    """
    >>> get_our_party_id('CPO')
    'CPO'
    >>> get_our_party_id('EMSP')
    'MSP'
    >>> get_our_party_id(None)  # Return the first one (for Credentials DELETE)
    'CPO'
    """
    _country_code, party_id = get_identity(role, identities).split('*')
    return party_id


# ic(ocpi_platform.is_hub, ocpi_platform.is_cpo, ocpi_platform.is_emsp)


@lru_cache(maxsize=None)
def get_our_party(role: OcpiRolesEnum = None, identities=ocpi_identities) -> Party:
    """
    >>> get_our_party(OcpiRolesEnum.CPO)
    Party(country_code='FI', party_id='CPO')
    >>> get_our_party(OcpiRolesEnum.EMSP)
    Party(country_code='FI', party_id='MSP')
    >>> get_our_party(None)  # Return the first one (for Credentials DELETE)
    Party(country_code='FI', party_id='CPO')
    """
    assert not role or isinstance(role, OcpiRolesEnum)
    country_code, party_id = get_identity(role.value if role else '', identities).split('*')
    return Party(country_code, party_id)
