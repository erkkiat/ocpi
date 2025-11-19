import pytz
from cachetools import cached, TTLCache
from django.utils.datetime_safe import datetime


import ocpi22.ocpi_logging as logging
import os
from typing import Union

from rest_framework.generics import get_object_or_404

from typing import TYPE_CHECKING

from ocpi22.models.cdrtoken import CdrToken
from ocpi22.ocpi.dataclasses import AdhocToken

if TYPE_CHECKING:
    from ocpi22.models.credentials import CredentialsRole

from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.util import generate_session_uid
from ocpi22.tokens.util import get_token_id
from ocpiconnector.party import Party


def get_token(token_id, ad_hoc_token) -> Union[Token, AdhocToken]:
    assert token_id or ad_hoc_token
    if token_id:
        token = get_object_or_404(Token, uid=token_id)
        return token
    return ad_hoc_token


def get_session(
    token: Union[Token, str], statuses=(Session.PENDING, Session.ACTIVE)
) -> Session:
    token_id = get_token_id(token)
    from ocpi22.tokens.auth import get_session_by_token_uid

    return get_session_by_token_uid(
        token_id, max_age_minutes=365 * 24 * 60, statuses=statuses
    )


class EvseOccupied(RuntimeError):
    pass


def create_session(
    location_id,
    evse_uid,
    connector_id,
    billed_to: Union[Party, str, "CredentialsRole"],
    credentials,
    token_id: Union[Token, str] = None,
    ad_hoc_token=None,
    uid=None,
    start_kwh=0.0,
    stop_kwh=0.0,
    session_status=Session.PENDING,
    authorization_reference="",
    reservation_id=None,
    authorization_method=None,
    currency=None,
    hub_session_id=None,
) -> Session:
    token: Token = (
        get_token(token_id, ad_hoc_token)
        if not isinstance(token_id, Token)
        else token_id
    )
    if not billed_to:
        billed_to = token.ocpi_master
    if isinstance(billed_to, str):
        billed_to = get_credentialsrole(party=Party(*billed_to.split("*")), create=True)
    if isinstance(billed_to, Party):
        billed_to = get_credentialsrole(party=billed_to, create=True)
    if not uid:
        uid = generate_session_uid()
    location = location_id
    if not isinstance(location_id, Location):
        location = Location.get_if_exists(uid=location_id, raise_exception=True)
    evse = evse_uid
    if not isinstance(evse_uid, Evse):
        evse = Evse.get_if_exists(uid=evse_uid, location=location, raise_exception=True)
    # The Connector may be selected later and the information gotten from the charger
    connector = (
        Connector.get_if_exists(uid=connector_id, evse=evse, raise_exception=True)
        if connector_id
        else None
    )

    from ocpi22.models.credentials import CredentialsRole

    if not (billed_to and billed_to != "*" and isinstance(billed_to, CredentialsRole)):
        raise ValueError("Unable to bill session without billed_to partner")

    currency = currency or os.environ.get("CPO_CURRENCY", "EUR")
    if connector and connector.tariff_ids:
        first_tariff = connector.tariff_ids.first()
        if first_tariff:
            currency = first_tariff.currency

    cdr_token, _created = CdrToken.objects.get_or_create(
        ocpi_master=billed_to,
        uid=token.uid,
        token_type=token.type,
        contract_id=token.contract_id,
    )
    params = dict(
        uid=uid,
        reservation_id=reservation_id,
        start_kwh=start_kwh,
        stop_kwh=stop_kwh,
        status=session_status,
        start_date_time=datetime.now(pytz.utc),
        last_updated=datetime.now(pytz.utc),
        cdr_token=cdr_token,
        auth_method=authorization_method,
        authorization_reference=authorization_reference or "",
        location=location,
        evse=evse,
        connector=connector,
        currency=currency,
        billed_to=billed_to,
        credentials=credentials,
        ocpi_master=location.ocpi_master,
        hub_session_id=hub_session_id,
    )
    params.pop("expiry_date", None)  # Todo: Finish implementing reservations

    session = Session.objects.create(**params)
    # No use to do session.send_update() yet, since pending sessions are not sent to the MSP

    logging.info(f"New session {session.uid} pending at {evse.evse_id}")
    return session


@cached(cache=TTLCache(maxsize=0, ttl=60 * 60))
def get_ocpi_token(session_id: str) -> str:
    """
    Get the OCPI token for the given session_id, which is the only token
    that is allowed to modify the data for this Session.
    """
    session = Session.objects.select_related(
        "ocpi_master", "ocpi_master__credentials"
    ).get(uid=session_id)
    from ocpi22.models.credentials import CredentialsRole

    ocpi_master = CredentialsRole.objects.get(pk=session.ocpi_master_id)
    return (
        ocpi_master.credentials.ours
        if getattr(ocpi_master, "credentials", None)
        else ""
    )
