from typing import Union, OrderedDict

from ocpi22.choices import OcpiRolesEnum, TokenType
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.token import Token
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpiconnector.ocpi_identities import get_our_party, get_our_credentialsrole


def get_admin_token() -> Token:
    our_country_code, our_party_id = Token.get_owner_identity().split('*')
    our_identity = Token.get_owner_identity()
    token, _created = Token.objects.get_or_create(
        ocpi_master=get_our_credentialsrole(OcpiRolesEnum.EMSP),
        uid=f'{our_identity}*T*ADMIN*TOKEN',
        defaults=dict(
            type='OTHER', contract_id='INTERNAL', issuer=our_identity, valid=True
        )
    )
    return token


def construct_adhoc_token(token_uid, contract_id, token_type=TokenType.APP_USER):
    our_party = get_our_party(OcpiRolesEnum.EMSP)
    credentialsrole = CredentialsRole(
        country_code=our_party.country_code, party_id=our_party.party_id, role=OcpiRolesEnum.EMSP
    )
    return Token(
        ocpi_master=credentialsrole,
        uid=token_uid,
        type=token_type,
        contract_id=contract_id,
        issuer=str(our_party),
        whitelist=Token.ALWAYS,
    )


def get_token_id(token: Union[Token, AdhocToken, str, int]) -> str:
    if isinstance(token, (Token, AdhocToken)):
        return token.uid
    if isinstance(token, (dict, OrderedDict)):
        return token.get('uid', '')
    return token


def get_token_type(token: Union[Token, AdhocToken, str, int], default_type) -> str:
    if isinstance(token, (Token, AdhocToken)):
        return token.type
    if isinstance(token, (dict, OrderedDict)):
        return token.get('type', default_type)
    return default_type
