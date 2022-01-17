import logging
import os
import uuid
from collections import namedtuple

from django.conf import settings
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.exceptions import NotFound
from rest_framework.generics import get_object_or_404

from ocpi22.cpo_api import authorize_token
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session
from ocpi22.models.token import Token


def get_token(token_id, ad_hoc_token):
    assert token_id or ad_hoc_token
    if token_id:
        token = get_object_or_404(Token, uid=token_id)
        return token
    CdrToken = namedtuple('CdrToken', ad_hoc_token)
    return CdrToken(**ad_hoc_token)


def create_session(location_id, evse_id, connector_id, token_id=None, ad_hoc_token=None,
                   authorization_reference=None, authorize=True) -> Session:
    # ic(location_id, evse_id, connector_id, token_id, ad_hoc_token)
    token = get_token(token_id, ad_hoc_token)
    location = Location.get_if_exists(uid=location_id)
    if not location:
        raise NotFound(f'Location {location_id} is not in our database')
    evse = get_object_or_404(Evse, uid=evse_id, location=location)
    location = evse.location
    # ic(token, evse, location)
    if location.uid != location_id:
        raise NotFound("Location doesn't match EVSE")
    # The Connector may be selected later and the information gotten from the charger
    connector = get_object_or_404(Connector, uid=connector_id, evse=evse) if connector_id else None
    auth_method = 'COMMAND'
    if authorize:
        auth_method = authorize_token(token)
        if not auth_method:
            raise exceptions.PermissionDenied(f'Token {token} was not authorized for use by MSP at this time')
    # noinspection PyUnresolvedReferences
    active_sessions = Session.objects.filter(evse=evse, status__in=('ACTIVE', 'PENDING'))
    if active_sessions.count():
        logging.warning(f'New session starting, invalidating incomplete sessions at {evse.evse_id}: '
                        f'{",".join([str(s) for s in active_sessions])}')
        active_sessions.update(status='INVALID')

    # noinspection PyUnresolvedReferences
    session = Session.objects.create(
        country_code=settings.COUNTRY_CODE,
        party_id=settings.PARTY_ID,
        uid=uuid.uuid4().hex,
        kwh=0.0,
        start_date_time=timezone.now(),
        cdr_token_uid=token.uid,
        cdr_token_type=token.type,
        cdr_token_contract_id=token.contract_id,
        auth_method=auth_method,
        authorization_reference=authorization_reference,
        location=location,
        evse=evse,
        connector=connector,
        currency=os.environ.get('CPO_CURRENCY', 'EUR')
    )
    if active_sessions.count():
        # Todo: put this on error list
        pass

    # Todo: send update to MSP
    return session
