import pytz
from django.utils.datetime_safe import datetime

import ocpi22.logging as logging
import os
from collections import namedtuple
from typing import Union

from django.conf import settings
from django.db.models import QuerySet
from rest_framework import exceptions
from rest_framework.generics import get_object_or_404

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ocpi22.models.credentials import CredentialsRole

from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.choices import AuthorizationEnum, OcpiRolesEnum
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.util import generate_session_uid
from ocpi22.tokens.auth import TokenAuthorization, get_session_by_adhoc_token
from ocpi22.tokens.util import get_token_id
from ocpiconnector.ocpi_identities import Party, get_our_credentialsrole


def get_token(token_id, ad_hoc_token):
    assert token_id or ad_hoc_token
    if token_id:
        token = get_object_or_404(Token, uid=token_id)
        return token
    CdrToken = namedtuple('CdrToken', ad_hoc_token)
    return CdrToken(**ad_hoc_token)


def get_session(token: Union[Token, str], statuses=(Session.PENDING, Session.ACTIVE)) -> Session:
    token_id = get_token_id(token)
    return get_session_by_adhoc_token(token_id,
                                      max_age_minutes=365 * 24 * 60,  # Maximum charge time: 1 year :)
                                      statuses=statuses)


class EvseOccupied(RuntimeError):
    pass


def create_session(location_id, evse_uid, connector_id, billed_to: Union[Party, str, "CredentialsRole"], credentials,
                   internal_reference=None, token_id: Union[Token, str] = None, ad_hoc_token=None,
                   uid=None, start_kwh=0.0, stop_kwh=0.0, session_status=Session.PENDING,
                   authorization_reference='', reservation_id=None, authorization_method=None, currency=None,
                   *_args, **kwargs
                   ) -> Session:
    if isinstance(billed_to, str):
        billed_to = get_credentialsrole(party=Party(*billed_to.split('*')))
    if isinstance(billed_to, Party):
        billed_to = get_credentialsrole(party=billed_to)
    if not uid:
        uid = generate_session_uid()
    token: Token = get_token(token_id, ad_hoc_token) if not isinstance(token_id, Token) else token_id
    location = location_id
    if not isinstance(location_id, Location):
        location = Location.get_if_exists(uid=location_id, raise_exception=True)
    evse = evse_uid
    if not isinstance(evse_uid, Evse):
        evse = Evse.get_if_exists(uid=evse_uid, location=location, raise_exception=True)
    # The Connector may be selected later and the information gotten from the charger
    connector = Connector.get_if_exists(uid=connector_id, evse=evse, raise_exception=True) if connector_id else None
    if not authorization_method:
        from ocpi22.tokens.auth import authorize_token
        authorization: TokenAuthorization = authorize_token(token.uid, location)
        if not authorization or authorization.allowed != AuthorizationEnum.ALLOWED:
            msg = f'Token {token} is not authorized for use by MSP at this time: ' \
                  f'{authorization.info if authorization else ""}'
            logging.error(msg)
            raise exceptions.PermissionDenied(msg)
        authorization_method, authorization_reference = authorization.auth_method, authorization.authorization_reference
    else:
        authorization_method = authorization_method or Session.COMMAND

    # Make sure there are no active Sessions in progress
    active_sessions = Session.objects.filter(evse=evse, status__in=('ACTIVE', 'PENDING'))
    if active_sessions.exists():
        logging.error(f'Cannot start a new Session because there are {active_sessions.count()} '
                      f'active sessions at EVSE {evse.evse_id}: {",".join([s.uid for s in active_sessions])}')
        raise EvseOccupied('Cannot start a new session because there is an active charging session '
                           f'{active_sessions.first().uid} in progress.')

    assert billed_to, 'Unable to bill session without billed_to'

    currency = currency or os.environ.get('CPO_CURRENCY', 'EUR')
    if connector and connector.tariff_ids:
        # Is there some other currency specified in the Tariff for this Connector?
        first_tariff = connector.tariff_ids.first()
        if first_tariff:
            currency = first_tariff.currency

    params = dict(
        uid=uid,
        reservation_id=reservation_id,
        internal_reference=internal_reference,
        start_kwh=start_kwh,
        stop_kwh=stop_kwh,
        status=session_status,
        start_date_time=datetime.now(pytz.utc),
        last_updated=datetime.now(pytz.utc),
        cdr_token_uid=token.uid,
        cdr_token_type=token.type,
        cdr_token_contract_id=token.contract_id,
        auth_method=authorization_method,
        authorization_reference=authorization_reference or '',
        location=location,
        evse=evse,
        connector=connector,
        currency=currency,
        billed_to=billed_to,
        credentials=credentials,
        ocpi_master=get_our_credentialsrole(OcpiRolesEnum.CPO)
    )
    params.update(kwargs)
    params.pop('expiry_date', None)  # Todo: Finish implementing reservations

    session = Session.objects.create(**params)
    # No use to do session.send_update() yet, since pending sessions are not sent to the MSP

    logging.info(f'New session {session.uid} pending at {evse.evse_id}')
    return session


def get_active_sessions(evse) -> QuerySet:
    from ocpi22.models.session import Session
    # noinspection PyUnresolvedReferences
    return Session.objects.filter(evse=evse, status=Session.ACTIVE)
