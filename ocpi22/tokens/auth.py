import celery
import requests
from celery.result import GroupResult
from django.conf import settings
from icecream import ic
from rest_framework import status
from rest_framework.exceptions import ValidationError

import ocpi22.logging as logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional, Union

from cachetools.func import ttl_cache
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from ocpi22.choices import OcpiModuleEnum, OcpiRolesEnum, MessageTexts, AuthorizationEnum
from ocpi22.models.credentials import find_endpoints_by_roles
from ocpi22.models.location import Location
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.ocpi.util import ocpi_post, Ocpi
from ocpi22.routing import find_route, Route
from ocpi22.tasks import send_ocpi_request
from ocpiconnector.ocpi_identities import get_our_party, Party
from ocpiconnector.util import Timer


@receiver(post_save, sender=Token)
def token_post_save(sender, instance: Token, *_args, **_kwargs):
    # In case there is an outdated authorization in the cache
    authorize_token.cache_clear()
    _authorize_token.cache_clear()
    _get_authorization_from_sessions.cache_clear()


def get_session_by_adhoc_token(token_uid: str, max_age_minutes,
                               statuses=(Session.PENDING, Session.ACTIVE)) -> Optional[Session]:
    # ic()
    time_start = timezone.now() - timedelta(minutes=max_age_minutes)
    # ic(token_uid, timespan, timezone.now())
    sessions = Session.objects.filter(
        Q(cdr_token_uid=token_uid) & Q(status__in=statuses) & Q(created__gte=time_start)
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
    token: Token
    party: Party
    authorization_reference: str
    auth_method: str

    def __bool__(self):
        return bool(self.auth_method)


@dataclass(eq=True, frozen=True)
class AuthorizationResult:
    status_code: int
    data: dict

    def __bool__(self):
        return bool(self.auth_method)

    def json(self) -> dict:
        return self.data

    @property
    def allowed(self) -> str:
        return self.data.get('data', {}).get('allowed')


def authorize_with_all_msps(token: str, location: Location) -> Optional[TokenAuthorization]:
    # do_authorization(token, location, route)
    parties = find_endpoints_by_roles((OcpiRolesEnum.EMSP.value, OcpiRolesEnum.HUB.value), OcpiModuleEnum.TOKENS)
    # ic(parties)
    authorize_calls = []
    for url, token_base64, country_code, party_id, credentials in parties:
        try:
            route = find_route(credentials, OcpiModuleEnum.TOKENS)
            to = Party(country_code, party_id)
            sender = get_our_party(OcpiRolesEnum.CPO)
            if settings.BACKGROUND_SEND:
                authorize_calls.append(
                    send_ocpi_request.s(
                        dict(
                            location_id=location.uid,
                            evse_uids=[e.uid for e in location.evses.all()]
                        ) if location else dict(),
                        f'{route.url}/{token}/authorize', route.token_base64,
                        to.country_code, to.party_id, sender.country_code, sender.party_id, 'post'
                    )
                )
            else:
                authorization = do_authorization(token, location, route, to=to)
                if authorization and authorization.allowed == AuthorizationEnum.ALLOWED.value:
                    return authorization
        except requests.exceptions.ConnectionError as e:
            logging.error(f'Unable to send Token authorization request to {to}: {e}')
            continue
    if authorize_calls:
        # ic(authorize_calls)
        job = celery.group(authorize_calls)
        results: GroupResult = job.apply_async()
        # ic(job, results)
        delay = .3
        for i in range(int(20 / delay)):
            try:
                # ic(i)
                for result in results:
                    response = result.get(timeout=delay)
                    # ic(response)
                    if response and response.get('status_code') == status.HTTP_200_OK:
                        sender = Party(**response.get('sender'))
                        result = AuthorizationResult(status_code=response.get('status_code'), data=response.get('json'))
                        logging.info(f'Token {token} was {result.allowed} by {sender}')
                        token = response.get('json', {}).get('data', {}).get('token', {})
                        country_code, party_id = token.get('country_code'), token.get('party_id')
                        # ic(sender, country_code, party_id)
                        if sender.country_code != country_code or sender.party_id != party_id:
                            logging.error(f'Someone at {sender} is trying to masquerade as {country_code}*{party_id}')
                        return None
                        return process_authorization_response(result, token, location, sender)
            except celery.exceptions.TimeoutError:
                continue
    return None


@ttl_cache(maxsize=1024, ttl=60)  # One minute cache, to make sure the query is made before 15-16 minutes has passed
def authorize_token(token: Union[str, Token], location=None) -> Optional[TokenAuthorization]:
    with Timer() as t:
        if not isinstance(token, Token):
            session = get_session_by_adhoc_token(token, max_age_minutes=15)
            if session:
                # Token is AD HOC
                return TokenAuthorization(
                    allowed='ALLOWED',
                    info=MessageTexts.get('TOKEN_ACCEPTED'),
                    token=AdhocToken(True, session.get_party(), token, Token.AD_HOC_USER),
                    party=session.get_party(),
                    authorization_reference=session.authorization_reference,
                    auth_method=session.auth_method,
                )

        # Not AD HOC, so Token should be found from database
        authorization = _authorize_token(token, location)
        if not authorization:
            # This is an unfamiliar Token, send OCPI Authorize request to all MSPs and see if anyone knows it
            authorization = authorize_with_all_msps(token, location)
    if authorization and t:
        logging.info(f'{authorization.party} responded to authorization request in {float(t):.1f} seconds')
    return authorization


@ttl_cache(maxsize=1024, ttl=14 * 60)
def _authorize_token(token: Union[Token, str], location=None) -> Optional[TokenAuthorization]:
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
            info=MessageTexts.get('TOKEN_ACCEPTED'),
            token=token,
            party=token.get_party(),
            authorization_reference='',
            auth_method=Session.WHITELIST,
        )

    # ic(token.get_party())
    route = find_route(token.get_party(), OcpiModuleEnum.TOKENS)
    # ic(route)
    if not route or not token:
        return None

    return do_authorization(token, location, route)


def do_authorization(token: Union[Token, str], location: Location, route: Route, to: Party = None) -> Optional[
    TokenAuthorization]:
    if isinstance(token, Token):
        to = to or token.get_party()
        token = token.uid
    result = ocpi_post(
        f'{route.url}/{token}/authorize',
        token_base64=route.token_base64,
        to=to,
        sender=get_our_party(OcpiRolesEnum.CPO),
        data=dict(
            location_id=location.uid,
            evse_uids=[e.uid for e in location.evses.all()]
        ) if location else dict()
    )
    return process_authorization_response(result, token, location, to)


def process_authorization_response(result, token, location, to) -> Optional[TokenAuthorization]:
    if result.status_code == status.HTTP_200_OK:
        data = result.json()
        authorization = data.get('data', data)
        allowed = authorization.get('allowed', AuthorizationEnum.NOT_ALLOWED)
    else:
        data = {}
        authorization = {}
        allowed = AuthorizationEnum.NOT_ALLOWED.value

    if allowed != AuthorizationEnum.ALLOWED.value:
        logging.warning(f'Result for authorizing token {token} at {location or "<not known>"} '
                        f'from {to} (HTTP {result.status_code}), '
                        f'response: {allowed}. ')
        return None
    if data.get('status_code') not in (Ocpi.OK, Ocpi.ClientError.UNKNOWN_TOKEN):
        logging.error(f'Token {token} OCPI authorization request returned an error: {data}')
        return None
    try:
        token = Token(**authorization.get('token', {}))
    except (ValidationError, ValueError) as e:
        logging.error(f'Cannot read Token data from authorization response from {to}: {e}')
        return None
    return TokenAuthorization(
        allowed=allowed,
        info=authorization.get('info', ''),
        token=token,
        party=token.get_party(),
        authorization_reference=authorization.get('authorization_reference'),
        auth_method=Session.AUTH_REQUEST,
    )
