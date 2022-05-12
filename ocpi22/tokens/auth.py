import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional, Union

from cachetools.func import ttl_cache
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from ocpi22.choices import OcpiModuleEnum, OcpiRolesEnum, MessageTexts
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi.util import ocpi_post
from ocpi22.routing import find_route

from ocpiconnector.ocpi_identities import get_our_party, Party


@receiver(post_save, sender=Token)
def token_post_save(sender, instance: Token, *_args, **_kwargs):
    # In case there is an outdated authorization in the cache
    authorize_token.cache_clear()
    _authorize_token.cache_clear()
    _get_authorization_from_sessions.cache_clear()


def get_session_by_adhoc_token(token_uid: str, max_age_minutes) -> Optional[Session]:
    # ic()
    time_start = timezone.now() - timedelta(minutes=max_age_minutes)
    # ic(token_uid, timespan, timezone.now())
    sessions = Session.objects.filter(
        Q(cdr_token_uid=token_uid) & Q(status__in=[Session.PENDING, Session.ACTIVE]) & Q(created__gte=time_start)
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
    allowed: str
    info: list
    token_id: str
    token_type: str
    party: Party
    authorization_reference: str
    auth_method: str

    def __bool__(self):
        return bool(self.auth_method)


@ttl_cache(maxsize=1024, ttl=60)  # One minute cache, to make sure the query is made before 15-16 minutes has passed
def authorize_token(token: Union[str, Token], location=None) -> Optional[TokenAuthorization]:
    if not isinstance(token, Token):
        session = get_session_by_adhoc_token(token, max_age_minutes=15)
        if session:
            # Token is AD HOC
            return TokenAuthorization(
                allowed='ALLOWED',
                info=MessageTexts.TOKEN_ACCEPTED,
                token_id=token,
                token_type=session.cdr_token_type,
                party=session.get_party(),
                authorization_reference=session.authorization_reference,
                auth_method=session.auth_method,
            )

    # Not AD HOC, so Token should be found from database
    return _authorize_token(token)


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
            allowed='ALLOWED',
            info=MessageTexts.TOKEN_ACCEPTED,
            token_id=token.uid,
            token_type=Token.RFID,
            party=token.get_party(),
            authorization_reference='',
            auth_method=Session.WHITELIST,
        )

    # ic(token.get_party())
    route = find_route(token.get_party(), OcpiModuleEnum.TOKENS)
    # ic(route)
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
        allowed=allowed,
        info=authorization.get('info', ''),
        token_id=token.uid,
        token_type=token.type,
        party=token.get_party(),
        authorization_reference=authorization.get('authorization_reference'),
        auth_method=Session.AUTH_REQUEST,
    )
