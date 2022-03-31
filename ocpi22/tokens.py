import logging

from cachetools.func import ttl_cache
from django.db.models.signals import post_save
from django.dispatch import receiver
from icecream import ic

from ocpi22.choices import OcpiModuleEnum, OcpiRolesEnum
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi_util import ocpi_post
from ocpi22.routing import find_route

from ocpiconnector.ocpi_identities import get_our_party


@receiver(post_save, sender=Token)
def token_post_save(sender, instance: Token, *_args, **_kwargs):
    # In case there is an outdated authorization in the cache
    authorize_token.cache_clear()


@ttl_cache(maxsize=128, ttl=15 * 60)
def authorize_token(token, location=None) -> (str, str):
    """
    Request authorization for a token we know, and consider that authorization valid for the next 15 minutes
    (OCPI requirement)
    """
    ic()
    if not isinstance(token, Token):
        token: Token = Token.get_if_exists(uid=token)
    if not token:
        return None, None
    if token.whitelist == Token.ALWAYS:
        return Session.WHITELIST, ''

    route = find_route(token.get_party(), OcpiModuleEnum.TOKENS)
    ic(route)

    location_references = dict(
        location_id=location.uid,
        evse_uids=[e.uid for e in location.evses.all()]
    )
    result = ocpi_post(
        f'{route.url}/{token.uid}/authorize',
        token_base64=route.token_base64,
        to=token.get_party(),
        sender=get_our_party(OcpiRolesEnum.CPO),
        data=dict(LocationReferences=location_references) if location else dict()
    )
    data = result.json()
    authorization = data.get('data', {}).get('AuthorizationInfo', {})
    allowed = authorization.get('allowed')
    if result.status_code > 400 or allowed != Token.ALLOWED:
        logging.warning(f'No authorization for token {token_uid} at {location or "<not known>"} '
                        f'from {endpoint.credentials.party()} (HTTP {result.status_code}), '
                        f'response: {allowed}. ')
        # raise exception.PermissionDenied("You don't have enough balance on your account.")
    if result.status_code == 200:
        # ic(data)
        return Session.AUTH_REQUEST, authorization.get('authorization_reference')

    return False, False


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
