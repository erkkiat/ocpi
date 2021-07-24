import os
import uuid

from django.utils import timezone
from icecream import ic
from rest_framework import exceptions
from rest_framework.exceptions import NotFound
from rest_framework.generics import get_object_or_404

from ocpi22.cpo_api import authorize_token
from ocpi22.models import Session, Token, Evse, Connector


def start_session(location_id, evse_id, connector_id, token_id) -> Session:
    ic(location_id, evse_id, connector_id, token_id)
    token = get_object_or_404(Token, uid=token_id)
    evse = get_object_or_404(Evse, uid=evse_id)
    location = evse.location
    if location != location_id:
        raise NotFound("Location doesn't match EVSE")
    connector = get_object_or_404(Connector, uid=connector_id, evse=evse)
    auth_method = authorize_token(token)
    if not auth_method:
        raise exceptions.PermissionDenied(f'Token {token} was not authorized for use by MSP at this time')
    active_session = Session.objects.filter(evse=evse, status__in=('ACTIVE', 'PENDING'))
    if active_session.count():
        ic('Invalidating incomplete sessions', ",".join([str(s) for s in active_session]))
        active_session.update(status='INVALID')

    session = Session.objects.create(
        country_code='FI',
        party_id=os.environ.get('CPO_PARTY_ID', 'XXX'),
        uid=uuid.uuid4(),
        kwh=0.0,
        start_date_time=timezone.now(),
        cdr_token=token,
        auth_method=auth_method,
        location=location,
        evse=evse,
        connector=connector,
        currency=os.environ.get('CPO_CURRENCY', 'EUR')
    )

    if active_session.count():
        # Todo: put this on error list
        pass

    # Todo: send update to MSP
    return session
