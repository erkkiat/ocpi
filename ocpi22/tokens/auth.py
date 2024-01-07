from urllib.parse import urljoin

import pytz
import requests
from django.utils.datetime_safe import datetime
from django.utils.safestring import mark_safe
from rest_framework import status
from rest_framework.exceptions import ValidationError

import ocpi22.logging as logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional, Union, OrderedDict

from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver

from ocpi22.tokens.token_async import authorize_with_all_msps_sync
from ocpi22.choices import OcpiModuleEnum, OcpiRolesEnum, MessageTexts, AuthorizationEnum, TokenType
from ocpi22.messages import messages
from ocpi22.models.location import Location
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.ocpi.util import ocpi_post, Ocpi
from ocpi22.routing import find_route, Route
from ocpiconnector.ocpi_identities import get_our_party, Party
from ocpiconnector.util import Timer
from util import with_trailing_slash, DistributedCache


@receiver(post_save, sender=Token)
def token_post_save(sender, instance: Token, *_args, raw, **_kwargs):
    if raw:
        return
    # In case there is an outdated authorization in the cache
    _authorize_token.cache_clear()
    _get_authorization_from_sessions.cache_clear()


def get_session_by_adhoc_token(token_uid: str, max_age_minutes,
                               statuses=(Session.PENDING, Session.ACTIVE)) -> Optional[Session]:
    """
    Get the most recent session for a given token within the last max_age_minutes
    @param token_uid: Token UID, not Token.pk
    @param max_age_minutes: How old the session can be
    @param statuses: Which Token statuses to look for
    @return: Session or if not found, None
    """
    time_start = datetime.now(pytz.utc) - timedelta(minutes=max_age_minutes)
    sessions = Session.objects.filter(
        Q(cdr_token_uid=token_uid) & Q(status__in=statuses) & Q(created__gte=time_start)
    ).order_by('-created')
    if sessions.exists():
        most_recent_session = sessions.first()
        return most_recent_session
    return None


@DistributedCache(expiration=60)  # One minute cache, to make sure the query is made before 15-16 minutes has passed
def _get_authorization_from_sessions(token_uid) -> (Party, str, str, str):
    session = get_session_by_adhoc_token(token_uid, max_age_minutes=15)
    if session:
        return session.auth_method, session.authorization_reference, session.get_party(), session.cdr_token_type
    return None, None, None, None


@dataclass(eq=True, frozen=True)
class TokenAuthorization:
    # Mandatory fields
    allowed: str
    token: Union[Token, AdhocToken, None]

    # Optional fields
    responding_party: Party = field(default_factory=Party)
    authorization_reference: str = ''
    auth_method: str = ''
    location: dict = field(default_factory=dict)
    info: list = field(default_factory=list)

    def __bool__(self):
        return bool(self.auth_method)

    @property
    def is_positive(self):
        return self.allowed == AuthorizationEnum.ALLOWED

    def get_token_party(self):
        if self.token:
            if isinstance(self.token, Token):
                return self.token.get_party()
            if isinstance(self.token, (dict, OrderedDict)):
                return f"{self.token.get('country_code', '--')}*{self.token.get('party_id', '---')}"
        return Party()

    def get_http_status(self) -> int:
        return dict(
            ALLOWED=status.HTTP_200_OK,
            BLOCKED=status.HTTP_401_UNAUTHORIZED,
            EXPIRED=status.HTTP_401_UNAUTHORIZED,
            NO_CREDIT=status.HTTP_401_UNAUTHORIZED,
            NOT_ALLOWED=status.HTTP_401_UNAUTHORIZED,
        ).get(self.allowed, status.HTTP_401_UNAUTHORIZED)

    def get_status_message(self) -> str:
        return dict(
            ALLOWED='Success',
            BLOCKED='Your charging token is blocked',
            EXPIRED='Your charging token is not valid at the moment',
            NO_CREDIT='Your charging token has no credit left',
            NOT_ALLOWED='Your charging token is not allowed to charge at this location',
        ).get(self.allowed, 'Unknown error')

    def get_language(self) -> str:
        return self.token.get('language', 'en') if self.token else 'en'


def authorize_token(token: Union[str, Token], location=None, request=None) -> Optional[TokenAuthorization]:
    with Timer() as t:
        if not isinstance(token, Token):
            session = get_session_by_adhoc_token(token, max_age_minutes=15)
            if session:
                # Token is AD HOC
                logging.info(f'Pre-existing Session {session.uid} '
                             f'with authorization {session.authorization_reference}', request=request)
                messages.success(request, mark_safe(f'This Token, <b>{token}</b> has been authorized '
                                                    f'earlier by MSP {session.billed_to} and the '
                                                    f'authorization was cached in the system.'))
                if not session.authorization_reference:
                    raise ValueError(f'Session {session.uid} is missing authorization_reference')
                return TokenAuthorization(
                    allowed='ALLOWED',
                    info=MessageTexts.get('TOKEN_ACCEPTED'),
                    token=AdhocToken(True, session.get_party(), token, TokenType.AD_HOC_USER),
                    responding_party=session.get_party(),
                    authorization_reference=session.authorization_reference,
                    auth_method=session.auth_method,
                )

        # Not AD HOC, so Token should be found from database
        authorization = _authorize_token(token, location, request=request)
        if authorization is None:
            # This is an unfamiliar Token, send OCPI Authorize request to all MSPs and see if anyone knows it
            messages.info(request, 'This Token is not in our database, '
                                   'so an authorization request was sent to all MSPs connected to us.')
            authorization = authorize_with_all_msps_sync(token, location)
    if authorization.is_positive and authorization.authorization_reference:
        messages.info(request,
                      mark_safe(f'<b>"{authorization.get_token_party()}"</b> responded <b>"{authorization.allowed}"</b> and '
                      f'generated the authorization reference <b>"{authorization.authorization_reference}"</b> '
                      'for this specific session. '
                      'It is the way to connect the record in the MSP database to the record in the CPO database. '
                      'After the charging session is finished, the MSP will receive the Charge Detail Record, which '
                      'has an authorization reference matching the one stored by the MSP internally.'))
    return authorization


@DistributedCache(expiration=15*60)  # 15 minutes cache, required by OCPI 2.2.1 spec
def _authorize_token(token: Union[Token, str], location=None, request=None) -> Optional[TokenAuthorization]:
    """
    Request authorization for a token we know, and consider that authorization valid for the next 15 minutes
    (OCPI requirement)
    """
    if not isinstance(token, Token):
        token: Token = Token.get_if_exists(uid=token)
    if not token or not token.valid:
        return None
    if token.whitelist == Token.ALWAYS:
        logging.info(f'Token {token} is whitelisted, no authorization request sent', request=request)
        return TokenAuthorization(
            allowed=Token.ALLOWED,
            token=token,
            info=MessageTexts.get('TOKEN_ACCEPTED'),
            auth_method=Session.WHITELIST,
        )

    # ic(token.get_party())
    route = find_route(token.get_party(), OcpiModuleEnum.TOKENS)
    # ic(route)
    if not route or not token:
        logging.warning(f'Route ({route}) or Token ({token}) missing, cannot authorize Token', request=request)
        return None

    return send_authorization_request(token, location, route, request=request)


def send_authorization_request(token: Union[Token, str], location: Location, route: Route, to: Party = None,
                     request=None) -> Optional[TokenAuthorization]:
    if isinstance(token, Token):
        to = to or token.get_party()
        token = token.uid
    url = urljoin(with_trailing_slash(route.url), f'{token}/authorize')
    result: requests.Response = ocpi_post(
        url=url,
        token_base64=route.token_base64,
        to=to,
        sender=get_our_party(OcpiRolesEnum.CPO),
        data=dict(
            location_id=location.uid,
            evse_uids=[e.uid for e in location.evses.all()]
        ) if location else dict()
    )
    logging.info(f'Authorization request to {to} finished in {result.elapsed}.')
    messages.info(request, 'The authorization request to '
                           f'{to} finished in {result.elapsed}. '
                           'Positive authorizations are cached for 15 minutes.')
    response = process_authorization_response(result, token, location, to, request=request)

    func = {
        AuthorizationEnum.ALLOWED.value: messages.success,
    }.get(response.allowed, messages.error)
    func(request, f'Response for OCPI authorization request was "{response.allowed}".')

    return response


def process_authorization_response(result, token, location, to, request=None) -> Optional[TokenAuthorization]:
    if result.status_code == status.HTTP_200_OK:
        data = result.json()
        authorization = data.get('data', data)
        allowed = authorization.get('allowed', AuthorizationEnum.NOT_ALLOWED)
    else:
        data = {}
        authorization = {}
        allowed = AuthorizationEnum.NOT_ALLOWED

    if allowed != AuthorizationEnum.ALLOWED:
        logging.warning(f'Result for authorizing token {token} at {location or "<not known>"} '
                        f'from {to} (HTTP {result.status_code}), '
                        f'response: {allowed}. ', request=request)
        messages.error(request, f'Token {token} was not authorized by {to}: {allowed}.')
        return TokenAuthorization(
            allowed=allowed,
            info=authorization.get('info', []),
            token=token,
            responding_party=token.get_party() if not isinstance(token, str) else Party('', ''),
            authorization_reference=authorization.get('authorization_reference', ''),
            auth_method=Session.AUTH_REQUEST,
        )
    if data.get('status_code') not in (Ocpi.OK, Ocpi.ClientError.UNKNOWN_TOKEN):
        msg = f'Token {token} OCPI authorization request returned an error: {data}'
        # messages.error(request, msg)
        logging.error(msg, request=request)
        return TokenAuthorization(
            allowed=AuthorizationEnum.NOT_ALLOWED,
            info=authorization.get('info', []),
            token=token,
            responding_party=token.get_party(),
            authorization_reference=authorization.get('authorization_reference', ''),
            auth_method=Session.AUTH_REQUEST,
        )
    try:
        token_data = authorization.get('token', {})

        # Find the corresponding CredentialsRole or create one
        to = Party(token_data.pop('country_code', ''), token_data.pop('party_id', ''))
        token_data['ocpi_master'] = get_credentialsrole(None, to, create=True)

        token = Token(**token_data)
    except (ValidationError, ValueError) as e:
        msg = f'Cannot read Token data from authorization response from {to}: {e}'
        # messages.error(request, msg)
        logging.error(msg, request=request)
        return None

    return TokenAuthorization(
        allowed=allowed,
        info=authorization.get('info', []),
        token=token,
        responding_party=token.get_party(),
        authorization_reference=authorization.get('authorization_reference', ''),
        auth_method=Session.AUTH_REQUEST,
    )
