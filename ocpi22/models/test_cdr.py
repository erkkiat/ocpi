from datetime import timedelta

import pytest

from ocpi22.conftest import create_ocpi_session_with_tariff
from ocpi22.models.cdr import Cdr
from ocpi22.models.session import Session
from ocpi22.ocpi.serializers import CdrSerializer


@pytest.mark.django_db
def test_formatting_session_url_from_cdr(completed_session):
    session = completed_session
    cdr = Cdr.objects.get(session_id=session.uid)
    assert cdr.session_id == session.uid
    assert cdr.ocpi_master == session.ocpi_master


@pytest.mark.django_db
def test_cdr_charging_periods_initialized_correctly_from_session_with_default_charging_period(
    completed_session,
):
    session = completed_session
    cdr = Cdr.objects.get(session_id=session.uid)
    assert CdrSerializer(cdr).data.get("charging_periods") == [
        {
            "dimensions": [
                {"type": "ENERGY", "volume": "20.0000"},
            ],
            "start_date_time": "2021-01-01T10:00:00Z",
            "tariff_id": "D9931A36-49A3-4C22-BA87-0E3C1792887B",
        }
    ]


@pytest.mark.django_db
def test_cdr_charging_periods_initialized_correctly_from_session_with_a_meter_values_call():
    default_ocpi_session = create_ocpi_session_with_tariff()
    default_ocpi_session.update_charging_periods(
        kwh=10,
        soc=50,
        power=120,
        timestamp=default_ocpi_session.start_date_time + timedelta(minutes=1),
    )
    default_ocpi_session.status = Session.COMPLETED
    default_ocpi_session.save()

    cdr = Cdr.objects.get(session_id=default_ocpi_session.uid)
    assert CdrSerializer(cdr).data.get("charging_periods") == [
        {
            "dimensions": [
                {"type": "ENERGY", "volume": "10.0000"},
                {"type": "STATE_OF_CHARGE", "volume": "50.0000"},
                {"type": "POWER", "volume": "120.0000"},
                {
                    "type": "TIME",
                    "volume": "0.0167",
                },
            ],
            "start_date_time": "2021-01-01T10:00:00Z",
            "tariff_id": "D9931A36-49A3-4C22-BA87-0E3C1792887B",
        }
    ]
