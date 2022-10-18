import logging
import os
import uuid
from collections import namedtuple
from typing import Union

from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.generics import get_object_or_404

from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.choices import AuthorizationEnum
from ocpi22.ocpi.util import generate_session_uid
from ocpi22.tokens.auth import TokenAuthorization, get_session_by_adhoc_token
from ocpi22.tokens.util import get_token_id


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


def create_session(location_id, evse_uid, connector_id, billed_to, credentials,
                   internal_reference=None, token_id=None, ad_hoc_token=None,
                   uid=None, start_kwh=0.0, stop_kwh=0.0, session_status=Session.PENDING,
                   authorize_from_msp=True, authorization_reference='', reservation_id=None, *args, **kwargs
                   ) -> Session:
    # ic(location_id, evse_uid, connector_id, token_id, ad_hoc_token)
    if not uid:
        uid = generate_session_uid()
    token = get_token(token_id, ad_hoc_token) if not isinstance(token_id, Token) else token_id
    location = location_id
    if not isinstance(location_id, Location):
        location = Location.get_if_exists(uid=location_id, raise_exception=True)
    evse = evse_uid
    if not isinstance(evse_uid, Evse):
        evse = Evse.get_if_exists(uid=evse_uid, location=location, raise_exception=True)
    # The Connector may be selected later and the information gotten from the charger
    connector = Connector.get_if_exists(uid=connector_id, evse=evse, raise_exception=True) if connector_id else None
    if authorize_from_msp:
        from ocpi22.tokens.auth import authorize_token
        authorization: TokenAuthorization = authorize_token(token, location)
        if not authorization or authorization.allowed != AuthorizationEnum.ALLOWED.value:
            msg = f'Token {token} is not authorized for use by MSP at this time: {authorization.info}'
            logging.error(msg)
            raise exceptions.PermissionDenied(msg)
        authorization_method, authorization_reference = authorization.auth_method, authorization.authorization_reference
    else:
        authorization_method = Session.COMMAND
    try:
        active_sessions = Session.objects.filter(evse=evse, status__in=('ACTIVE', 'PENDING'))
        if active_sessions.exists():
            logging.warning(f'New session overlaps existing, completing previous active sessions at {evse.evse_id}: '
                            f'{",".join([s.uid for s in active_sessions])}')
            for session in active_sessions:
                session.status = Session.COMPLETED
                session.save()  # This doesn't seem to send an update for some reason
                session.send_updates()
    except Exception as e:
        logging.error(f'{settings.HOSTNAME}: Inactivating overlapping sessions failed for EVSE {evse.uid}: {e}')

    our_country_code, our_party_id = Session.get_owner_identity().split('*')

    assert billed_to, 'Unable to bill session without billed_to'

    # noinspection PyUnresolvedReferences
    session = Session.objects.create(
        country_code=our_country_code,
        party_id=our_party_id,
        uid=uid,
        reservation_id=reservation_id,
        internal_reference=internal_reference,
        start_kwh=start_kwh,
        stop_kwh=stop_kwh,
        status=session_status,
        start_date_time=timezone.now(),
        cdr_token_uid=token.uid,
        cdr_token_type=token.type,
        cdr_token_contract_id=token.contract_id,
        auth_method=authorization_method,
        authorization_reference=authorization_reference or '',
        location=location,
        evse=evse,
        connector=connector,
        currency=os.environ.get('CPO_CURRENCY', 'EUR'),
        billed_to=billed_to,
        credentials=credentials
    )

    logging.info(f'New session {session.uid} pending at {evse.evse_id}')
    return session


def get_active_sessions(evse) -> QuerySet:
    from ocpi22.models.session import Session
    # noinspection PyUnresolvedReferences
    return Session.objects.filter(evse=evse, status=Session.ACTIVE)
