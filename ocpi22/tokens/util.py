from typing import Union

from ocpi22.choices import OcpiRolesEnum
from ocpi22.models.token import Token
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpiconnector.ocpi_identities import get_our_party


def get_admin_token() -> Token:
    our_country_code, our_party_id = Token.get_owner_identity().split('*')
    our_identity = Token.get_owner_identity()
    token, _created = Token.objects.get_or_create(
        country_code=our_country_code,
        party_id=our_party_id,
        uid=f'{our_identity}*T*ADMIN*TOKEN',
        defaults=dict(
            type='OTHER', contract_id='INTERNAL', issuer=our_identity, valid=True
        )
    )
    return token


def construct_adhoc_token(token_uid, contract_id, token_type=Token.APP_USER):
    our_party = get_our_party(OcpiRolesEnum.EMSP)
    return Token(
        country_code=our_party.country_code,
        party_id=our_party.party_id,
        uid=token_uid,
        type=token_type,
        contract_id=contract_id,
        issuer=str(our_party),
        whitelist=Token.ALWAYS,
    )


def get_token_id(token: Union[Token, AdhocToken, str, int]) -> str:
    if isinstance(token, Token) or isinstance(token, AdhocToken):
        return token.uid
    return token
