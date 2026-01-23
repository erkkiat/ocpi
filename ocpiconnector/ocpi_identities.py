import os
from typing import Optional

import cachetools
from cachetools import cached

from ocpi22.choices import ROLE_OPTIONS, OcpiRolesEnum
from django.conf import settings

from ocpiconnector.party import Party


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class OCPIIdentities(metaclass=Singleton):
    """
    Store the identities of this OCPI Platform in list and dict form for convenient access
    These tests rely on data in environment variables

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
        self._identities_list = list(
            [
                source.get(i) for i in ROLE_OPTIONS if source.get(i)
            ]  # Todo: ignore a false value in the source
        )
        for n in ROLE_OPTIONS:
            item = source.get(n)
            if item:
                self._identities_dict[n] = item

    def __len__(self):
        return len(self._identities_list)

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

    def get(self, item, default="*") -> str:
        return self._identities_dict[item] if item in self._identities_dict else default

    @property
    def roles(self):
        return self._identities_dict.keys()


ocpi_identities = OCPIIdentities()


class OCPIPlatform(metaclass=Singleton):
    is_hub = bool("HUB" in ocpi_identities)
    is_cpo = bool("CPO" in ocpi_identities)
    is_emsp = bool("EMSP" in ocpi_identities)


ocpi_platform = OCPIPlatform()
if len(ocpi_identities) > 1 and settings.ENV not in ["development", "test"]:
    raise ValueError(
        "This platform cannot handle multiple roles, "
        "since the object IDs can overlap when receiving objects from other platforms"
    )


@cached(cache=dict())
def get_our_identity(role: str = None, identities=ocpi_identities) -> str:
    """
    These tests rely on data in environment variables

    >>> get_our_identity('EMSP')
    'FI*MSP'
    >>> get_our_identity('CPO')
    'FI*CPO'
    >>> get_our_identity()
    'FI*CPO'

    @param role:
    @param identities:
    @return:
    """
    if not role:
        return list(identities.items())[0][1]
    return identities.get(role)


@cached(cache=dict())
def get_our_country_code(role: str = None, identities=ocpi_identities) -> str:
    """
    These tests rely on data in environment variables

    >>> get_our_country_code('CPO')
    'FI'
    >>> get_our_country_code('EMSP')
    'FI'
    >>> get_our_country_code(None)  # Return the first one (for Credentials DELETE)
    'FI'
    """
    country_code, _party_id = get_our_identity(role, identities).split("*")
    return country_code


@cached(cache=dict())
def get_our_party_id(role: str = None, identities=ocpi_identities) -> str:
    """
    These tests rely on data in environment variables

    >>> get_our_party_id('CPO')
    'CPO'
    >>> get_our_party_id('EMSP')
    'MSP'
    >>> get_our_party_id(None)  # Return the first one (for Credentials DELETE)
    'CPO'
    """
    _country_code, party_id = get_our_identity(role, identities).split("*")
    return party_id


@cached(cache=dict())
def get_our_party(role: OcpiRolesEnum = None, identities=ocpi_identities) -> Party:
    """
    These tests rely on data in environment variables

    >>> get_our_party(OcpiRolesEnum.CPO)
    Party(country_code='FI', party_id='CPO')
    >>> get_our_party(OcpiRolesEnum.EMSP)
    Party(country_code='FI', party_id='MSP')
    >>> get_our_party(None)  # Return the first one (for Credentials DELETE)
    Party(country_code='FI', party_id='CPO')
    """
    role = role.value if role else None
    country_code, party_id = get_our_identity(role if role else "", identities).split(
        "*"
    )
    return Party(country_code, party_id)


def create_credentialsrole(
    party: Party,
    business_name: str,
    website="",
    role=OcpiRolesEnum.UNKNO,
    credentials=None,
    pk=None,
) -> Optional["CredentialsRole"]:  # noqa: F821
    """
    Create a CredentialsRole object for the given party, business name, website and role.
    Use only for creating our own CredentialsRole objects. If you use this for other parties, they will not have
    any Credentials tokens set, and communication will not be possible.
    """
    from ocpi22.models.business_details import BusinessDetails
    from ocpi22.models.credentials import CredentialsRole

    bt, _created = BusinessDetails.objects.get_or_create(
        name__iexact=business_name, defaults=dict(name=business_name, website=website)
    )
    credentialsrole, _created = CredentialsRole.objects.get_or_create(
        country_code__iexact=party.country_code,
        party_id__iexact=party.party_id,
        credentials=credentials,
        defaults=dict(
            country_code=party.country_code,
            party_id=party.party_id,
            business_details=bt,
            role=role,
            pk=pk,
        ),
    )
    return credentialsrole


@cached(cache=cachetools.Cache(maxsize=len(ROLE_OPTIONS)))
def get_our_credentialsrole(
    role: OcpiRolesEnum,
) -> "CredentialsRole":  # noqa: F821
    """
    Get the CredentialsRole object which corresponds to our OCPI roles set in environment variables,
    creating it if necessary
    """
    from ocpi22.models.credentials import CredentialsRole

    our_party = get_our_party(role)
    try:
        return CredentialsRole.objects.get(
            country_code__iexact=our_party.country_code,
            party_id__iexact=our_party.party_id,
        )
    except CredentialsRole.DoesNotExist:
        business_name = os.environ.get("BUSINESS_NAME", "N/A")
        website = os.environ.get("BUSINESS_WEBSITE", None)
        return create_credentialsrole(our_party, business_name, website, role)
