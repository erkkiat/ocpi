import pytz
from django.conf import settings
from django.utils.datetime_safe import datetime
from rest_framework import status
from rest_framework.utils.serializer_helpers import ReturnDict

import ocpi22.ocpi_logging as logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional, Union, OrderedDict

from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver

from ocpi22.models import enum
from ocpi22.models.credentials import CredentialsRole
from ocpi22.tokens.services import TokenAuthorizationService
from ocpi22.tokens.token_async import authorize_with_msps_sync
from ocpi22.choices import (
    OcpiModuleEnum,
    MessageTexts,
    AuthorizationEnum,
    get_language,
    EndpointRoleEnum,
)
from ocpi22.messages import messages
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.routing import find_route, Route
from ocpiconnector.party import Party
from ocpiconnector.util import Timer
from util import DistributedCache, markdown_escape


@receiver(post_save, sender=Token)
def token_post_save(sender, instance: Token, *_args, raw, **_kwargs):
    if raw:
        return
    # In case there is an outdated authorization in the cache
    _authorize_token.cache_clear()
    _get_authorization_from_sessions.cache_clear()


def get_session_by_token_uid(
    token_uid: str, max_age_minutes, statuses=(Session.PENDING, Session.ACTIVE)
) -> Optional[Session]:
    """
    TO BE REPLACED BY get_or_create_session_by_token_uid()

    Get the most recent session for a given token within the last max_age_minutes
    @param token_uid: Token UID, not Token.pk
    @param max_age_minutes: How old the session can be
    @param statuses: Which Token statuses to look for
    @return: Session or if not found, None
    """
    time_start = datetime.now(pytz.utc) - timedelta(minutes=max_age_minutes)
    sessions = Session.objects.filter(
        Q(cdr_token__uid=token_uid)
        & Q(status__in=statuses)
        & Q(created__gte=time_start)
    ).order_by("-created")
    return sessions.first()


@DistributedCache(
    expiration=60
)  # One minute cache, to make sure the query is made before 15-16 minutes has passed
def _get_authorization_from_sessions(token_uid) -> (Party, str, str, str):
    session = get_session_by_token_uid(token_uid, max_age_minutes=15)
    if session:
        return (
            session.auth_method,
            session.authorization_reference,
            session.get_party(),
            session.cdr_token.type,
        )
    return None, None, None, None


@dataclass
class TokenAuthorization:
    # Mandatory fields
    allowed: str
    token: Union[Token, AdhocToken, None]

    # Optional fields
    responding_party: str = ""
    authorization_reference: str = ""
    auth_method: str = ""
    location: dict = field(default_factory=dict)
    info: list = field(default_factory=list)
    billed_to: str = ""
    msp: CredentialsRole = None
    status_text: str = ""
    hub_session_id: str = ""

    @property
    def route_via_hubject(self) -> bool:
        return self.responding_party == settings.HUBJECT_OPERATOR_ID

    @staticmethod
    def get_token_owner(token) -> Party:
        """
        >>> TokenAuthorization.get_token_owner(None)
        Party(country_code='', party_id='')
        >>> TokenAuthorization.get_token_owner(dict(country_code='FI', party_id='EON'))
        Party(country_code='FI', party_id='EON')

        @param token:
        @return:
        """
        if token:
            if isinstance(token, Token):
                return token.get_party()
            if isinstance(token, (dict, OrderedDict, ReturnDict)):
                return token.get("owner", "") or Party(
                    token.get("country_code", ""), token.get("party_id", "")
                )
        return Party()

    def __post_init__(self):
        self.billed_to = self.billed_to or str(self.get_token_owner(self.token))
        if self.is_positive and not self.is_billable:
            msg = f"Unable to determine who to bill for Token {self.token}"
            logging.error(msg, request=None)
            raise ValueError(msg)
        language = getattr(self.token, "language", "en") if self.token else "en"
        if self.info:
            self.status_text = get_language(language, self.info)

    def __bool__(self):
        return bool(self.auth_method)

    @property
    def is_billable(self):
        return self.is_positive and self.billed_to not in {"*", ""}

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
        return (
            status.HTTP_200_OK
            if self.allowed == AuthorizationEnum.ALLOWED
            else status.HTTP_401_UNAUTHORIZED
        )

    def get_status_message(self) -> str:
        return dict(
            ALLOWED="Success",
            BLOCKED="Your charging token is blocked",
            EXPIRED="Your charging token is not valid at the moment",
            NO_CREDIT="Your charging token has no credit left",
            NOT_ALLOWED="Your charging token is not allowed to charge (at this location)",
        ).get(self.allowed, "Unknown error")

    def get_language(self) -> str:
        return self.token.get("language", "en") if self.token else "en"


def authorize_token(
    token: Union[str, Token],
    location=None,
    request=None,
    max_age=15,
    rfid=False,
    evse_id=None,
) -> Optional[TokenAuthorization]:
    with Timer() as t:
        if not rfid and not isinstance(token, Token):
            token_uid = token
            session = get_session_by_token_uid(token_uid, max_age_minutes=max_age)
            if session:
                # Token is AD HOC
                logging.info(
                    f"Pre-existing Session **{markdown_escape(session.uid)}** "
                    f"with authorization **{markdown_escape(session.authorization_reference)}**",
                    request=request,
                )
                messages.success(
                    request,
                    f"This Token, **{markdown_escape(str(token_uid))}** has been authorized "
                    f"earlier by **{markdown_escape(str(session.billed_to))}** and the "
                    f"authorization was cached in the system.",
                )
                if not session.authorization_reference:
                    raise ValueError(
                        f"Session {session.uid} is missing authorization_reference"
                    )
                return TokenAuthorizationService.get_default_allowed_authorization(
                    session, token_uid
                )

        # Not AD HOC, so Token should be found from database
        authorization: TokenAuthorization = _authorize_token(
            token, location, request=request, evse_id=evse_id
        )
        if (
            authorization
            and authorization.is_positive
            and authorization.authorization_reference
        ):
            messages.info(
                request,
                f'**{markdown_escape(str(authorization.billed_to))}** responded **"{authorization.allowed}"** and '
                f'generated the authorization reference **"{markdown_escape(authorization.authorization_reference)}"** '
                "for this specific session. "
                "It is the way to connect the record in the MSP database to the record in the CPO database. "
                "After the charging session is finished, the MSP will receive the Charge Detail Record, which "
                "has an authorization reference matching the one stored by the MSP internally.",
            )
    if t:
        logging.info(f"Authorization took {t}", request=request)
    return authorization


# 15 minutes cache, required by OCPI 2.2.1 spec
# Don't cache negative responses, so that we can try again after updating payment method etc.
@DistributedCache(
    expiration=15 * 60,
    exclude=lambda x: x.allowed != AuthorizationEnum.ALLOWED
    if hasattr(x, "allowed")
    else True,
)
def _authorize_token(
    token: Union[Token, str], location=None, request=None, evse_id=None
) -> Optional[TokenAuthorization]:
    """
    Request authorization for a token we know, and consider that authorization valid for the next 15 minutes
    (OCPI requirement)
    """
    token_uid = token.uid if isinstance(token, Token) else token
    if isinstance(token, str):
        token: Token = Token.get_if_exists(uid__iexact=token)
    if not token:
        # This is an unfamiliar Token, send OCPI Authorize request to all MSPs and see if anyone knows it
        messages.info(
            request,
            "This Token is not in our database, "
            "so an authorization request was sent to all MSPs connected to us.",
        )
        return authorize_with_msps_sync(token_uid, location)
    assert isinstance(token, (Token, AdhocToken))
    if not token.valid:
        logging.warning(
            f"According to the current information we have locally, the Token {token_uid} is not valid."
        )
        return TokenAuthorization(allowed=AuthorizationEnum.NOT_ALLOWED, token=token)
    if token.whitelist == Token.ALWAYS:
        logging.info(
            f"Token {token} is whitelisted, no authorization request sent",
            request=request,
        )
        return TokenAuthorization(
            allowed=Token.ALLOWED,
            token=token,
            info=MessageTexts.get("TOKEN_ACCEPTED"),
            auth_method=enum.AuthMethodChoices.WHITELIST,
            billed_to=str(token.get_party()),
            msp=token.ocpi_master,
        )

    route: Route = find_route(
        token.get_party(), OcpiModuleEnum.TOKENS, role=EndpointRoleEnum.SENDER
    )
    if not route or not token:
        logging.warning(
            f"Route ({route}) or Token ({token}) missing, cannot authorize Token",
            request=request,
        )
        return None

    # Let's send the authorization request using the same code as when sending request to multiple MSPs
    # to keep things DRY
    parties = [
        (
            route.url,
            route.token_base64,
            route.to.country_code,
            route.to.party_id,
            route.credentials,
        )
    ]
    return authorize_with_msps_sync(token.uid, location, parties)
