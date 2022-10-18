from dataclasses import dataclass
from random import randint

from django.conf import settings
from django.utils.datetime_safe import datetime

import ocpi22.util


@dataclass(eq=True)
class Reservation:
    evse_pk: str
    connector_id: str
    ocpi_reservation_id: str
    ocpp_reservation_id: int
    expiry_date: datetime


reservation_store = ocpi22.RedisStore('rsv', expiration=settings.REMOTE_COMMAND_EXPIRATION)


def store_reservation(reservation: Reservation):
    if not reservation.ocpp_reservation_id:
        reservation.ocpp_reservation_id = randint(1, 2 << 31)
    assert all(
        (reservation.ocpi_reservation_id, bool(reservation.expiry_date))
    )
    reservation_store[reservation.ocpi_reservation_id] = reservation
    reservation_store[reservation.ocpp_reservation_id] = reservation


def get_reservation(reservation_id: str) -> Reservation:
    return reservation_store[reservation_id]
