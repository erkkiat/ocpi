import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from cachetools.func import ttl_cache
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from icecream import ic

from ocpi22.choices import OcpiModuleEnum, OcpiRolesEnum
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi_util import ocpi_post
from ocpi22.routing import find_route

from ocpiconnector.ocpi_identities import get_our_party, Party


@receiver(post_save, sender=Token)
def token_post_save(sender, instance: Token, *_args, **_kwargs):
    # In case there is an outdated authorization in the cache
    authorize_token.cache_clear()


def get_session_by_adhoc_token(token_uid: str, max_age_minutes) -> Optional[Session]:
    # ic()
    last_15_minutes = timezone.now() - timedelta(minutes=max_age_minutes)
    # ic(token_uid, last_15_minutes, timezone.now())
    # noinspection PyUnresolvedReferences
    sessions = Session.objects.filter(
        Q(cdr_token_uid=token_uid) & Q(status=Session.PENDING) & Q(created__gte=last_15_minutes)
    ).order_by('-created')
    if sessions.exists():
        session = sessions.first()
        # ic(session.get_party(), session.auth_method, session.authorization_reference)
        return session
    return None


@ttl_cache(maxsize=1024, ttl=60)  # One minute cache, to make sure the query is made before 15-16 minutes has passed
def _get_authorization_from_sessions(token_uid) -> (Party, str, str, str):
    session = get_session_by_adhoc_token(token_uid, max_age_minutes=15)
    if session:
        return session.auth_method, session.authorization_reference, session.get_party(), session.cdr_token_type
    return None, None, None, None


@dataclass(eq=True, frozen=True)
class TokenAuthorization:
    token_id: str
    token_type: str
    party: Party
    authorization_reference: str
    auth_method: str

    def __bool__(self):
        return bool(self.auth_method)


@ttl_cache(maxsize=1024, ttl=60)  # One minute cache, to make sure the query is made before 15-16 minutes has passed
def authorize_token(token_uid, location=None) -> Optional[TokenAuthorization]:
    session = get_session_by_adhoc_token(token_uid, max_age_minutes=15)
    if session:
        # Token is AD HOC
        return TokenAuthorization(
            token_id=token_uid,
            token_type=session.cdr_token_type,
            party=session.get_party(),
            authorization_reference=session.authorization_reference,
            auth_method=session.auth_method,
        )

    # Not AD HOC, so Token should be found from database
    return _authorize_token(token_uid)


@ttl_cache(maxsize=1024, ttl=14 * 60)
def _authorize_token(token, location=None) -> Optional[TokenAuthorization]:
    """
    Request authorization for a token we know, and consider that authorization valid for the next 15-1 minutes
    (OCPI requirement)
    """
    if not isinstance(token, Token):
        token: Token = Token.get_if_exists(uid=token)
    if not token or not token.valid:
        return None
    if token.whitelist == Token.ALWAYS:
        return TokenAuthorization(
            token_id=token.uid,
            token_type=Token.RFID,
            party=token.party(),
            authorization_reference='',
            auth_method=Session.WHITELIST,
        )

    ic(token.get_party())
    route = find_route(token.get_party(), OcpiModuleEnum.TOKENS)
    ic(route)
    if not route or not token:
        return None

    result = ocpi_post(
        f'{route.url}/{token.uid}/authorize',
        token_base64=route.token_base64,
        to=token.get_party(),
        sender=get_our_party(OcpiRolesEnum.CPO),
        data=dict(LocationReferences=dict(
            location_id=location.uid,
            evse_uids=[e.uid for e in location.evses.all()]
        )) if location else dict()
    )
    data = result.json()
    authorization = data.get('data', {}).get('AuthorizationInfo', {})
    allowed = authorization.get('allowed')
    if result.status_code > 400 or allowed != Token.ALLOWED:
        logging.warning(f'No authorization for token {token} at {location or "<not known>"} '
                        f'from {token.party()} (HTTP {result.status_code}), '
                        f'response: {allowed}. ')
        # raise exception.PermissionDenied("You don't have enough balance on your account.")
    return TokenAuthorization(
        token_id=token.uid,
        token_type=token.type,
        party=token.party(),
        authorization_reference=authorization.get('authorization_reference'),
        auth_method=Session.AUTH_REQUEST,
    )


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
