from dataclasses import dataclass
from random import randint

from django.conf import settings
from django.utils.datetime_safe import datetime

from util import RedisStore


@dataclass(eq=True)
class Reservation:
    evse_pk: str
    connector_id: str
    ocpi_reservation_id: str
    ocpp_reservation_id: int
    expiry_date: datetime


reservation_store = RedisStore('rsv', expiration=settings.REMOTE_COMMAND_EXPIRATION)


def store_reservation(reservation: Reservation):
    """
    Store the parameters of the received RESERVE_NOW command
    >>> store_reservation(Reservation('1', '2', '3', None, datetime(2020, 1, 1)))
    >>> a = get_reservation('3')
    >>> bool(a.get('ocpp_reservation_id'))
    True

    Please see more unittests in get_reservation()
    """
    if not reservation.ocpp_reservation_id:
        reservation.ocpp_reservation_id = randint(1, 2 << 31)
    assert all(
        (reservation.ocpi_reservation_id, bool(reservation.expiry_date))
    )
    reservation_store[reservation.ocpi_reservation_id] = reservation
    reservation_store[reservation.ocpp_reservation_id] = reservation


def get_reservation(reservation_id: str) -> Reservation:
    """
    >>> store_reservation(Reservation('1', '2', '3', 4, datetime(2020, 1, 1)))
    >>> get_reservation('3')
    {'evse_pk': '1', 'connector_id': '2', 'ocpi_reservation_id': '3', 'ocpp_reservation_id': 4, 'expiry_date': '2020-01-01 00:00:00'}
    >>> get_reservation(4)
    {'evse_pk': '1', 'connector_id': '2', 'ocpi_reservation_id': '3', 'ocpp_reservation_id': 4, 'expiry_date': '2020-01-01 00:00:00'}
    >>> get_reservation('5')
    Traceback (most recent call last):
    ...
    KeyError: 'No 5 stored for rsv'
    """
    return reservation_store[reservation_id]
