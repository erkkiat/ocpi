import logging

import pytest
import pytz
from datetime import datetime
from unittest.mock import Mock, patch

import time_machine

from ocpi22.models.session import ChargingPeriod, ChargingPeriodSerializer
from ocpi22.cpo.services import CdrService
from ocpi22.tests.factories import (
    ChargingPeriodFactory,
    OCPISessionFactory,
    TariffFactory,
    DefaultTariffsFactory,
    CdrTokenFactory,
)


@pytest.fixture
def mock_session():
    session = OCPISessionFactory(cdr_token=CdrTokenFactory())
    return session


@pytest.fixture
def expected_charging_periods_json():
    return [
        {
            "start_date_time": "2023-01-01T12:00:00Z",
            "tariff_id": "CP1",
            "dimensions": [
                {"type": "ENERGY", "volume": "10.0000"},
                {"type": "TIME", "volume": "1.5000"},
            ],
        },
        {
            "start_date_time": "2023-01-01T12:00:00Z",
            "tariff_id": "CP1",
            "dimensions": [
                {"type": "ENERGY", "volume": "10.0000"},
                {"type": "TIME", "volume": "1.5000"},
            ],
        },
    ]


@pytest.mark.django_db
def test_get_charging_periods_returns_valid_charging_periods_list(
    mock_session, expected_charging_periods_json
):
    tariff1 = TariffFactory(uid="CP1")
    charging_period = ChargingPeriodFactory.create_batch(
        2,
        start_date_time=datetime(2023, 1, 1, 12, 0, 0, tzinfo=pytz.UTC),
        tariff=tariff1,
    )
    mock_session.chargingperiods.set(charging_period)
    mock_session.save()

    result = CdrService._get_charging_periods(mock_session)
    assert result == expected_charging_periods_json


@pytest.mark.django_db
def test_get_charging_periods_creates_charging_periods_when_session_has_no_charging_periods(
    mock_session, caplog
):
    caplog.set_level(logging.ERROR)

    ChargingPeriod.objects.all().delete()
    result = CdrService._get_charging_periods(mock_session)

    assert len(result) == 1
    assert (
        f"No charging periods found for session {mock_session.uid} to create CDR."
        in caplog.text
    )
    assert len(ChargingPeriod.objects.all()) == 1


@pytest.mark.django_db
def test_get_cdr_tariffs_returns_a_list_of_tariffs_from_charging_periods():
    tariff1 = TariffFactory(uid="CP1")
    tariff2 = TariffFactory(uid="CP2")
    charging_periods_json = ChargingPeriodSerializer(
        [ChargingPeriodFactory(tariff=tariff1), ChargingPeriodFactory(tariff=tariff2)],
        many=True,
    ).data

    result = CdrService._get_cdr_tariffs(charging_periods_json, "IEC_62196_T2")

    assert result == [tariff1, tariff2]


@pytest.mark.django_db
def test_get_cdr_tariffs_skips_nonexistent_tariffs(caplog):
    caplog.set_level(logging.WARNING)
    tariff1 = TariffFactory(uid="CP1")
    tariff2 = TariffFactory(uid="CP2")
    charging_periods_json = ChargingPeriodSerializer(
        [ChargingPeriodFactory(tariff=tariff1), ChargingPeriodFactory(tariff=tariff2)],
        many=True,
    ).data

    # Change UID after creating the charging periods json.
    # This is not possible to happen irl (because of immutableTariffs) unless there is something wrong with the database.
    tariff2.uid = "NonExistentTariff"
    tariff2.save()

    standard = "IEC_62196_T2"

    CdrService._get_cdr_tariffs(charging_periods_json, standard)

    assert "Tariff with uid CP2 not found." in caplog.text


@pytest.mark.django_db
def test_get_cdr_tariffs_uses_default_tariffs_when_no_tariffs_found():
    charging_periods_json = ChargingPeriodSerializer(
        ChargingPeriodFactory(tariff=None)
    ).data

    standard = "IEC_62196_T2"
    tariff = TariffFactory(uid="DefaultTariff")
    DefaultTariffsFactory(standard=standard, tariffs=[tariff])

    result = CdrService._get_cdr_tariffs(charging_periods_json, standard)

    assert result[0] == tariff


@pytest.mark.django_db
def test_create_cdr_creates_and_returns_cdr(mock_session):
    tariff1 = TariffFactory(uid="CP1")
    charging_period = ChargingPeriodFactory(
        start_date_time=datetime(2023, 1, 1, 12, 0, 0, tzinfo=pytz.UTC), tariff=tariff1
    )
    mock_session.chargingperiods.set([charging_period])
    mock_session.save()

    result = CdrService._create_cdr(mock_session)

    assert result is not None
    assert result.session_id == mock_session.uid
    assert result.start_date_time == mock_session.start_date_time
    assert result.end_date_time == mock_session.end_date_time
    assert result.cdr_token.uid == mock_session.cdr_token.uid
    assert result.cdr_token.token_type == mock_session.cdr_token.token_type
    assert result.cdr_location.uid == mock_session.location.uid
    assert len(result.tariffs.all()) > 0
    assert result.charging_periods is not None
    assert result.total_energy == mock_session.kwh
    assert result.total_cost_excl_vat == mock_session.total_cost_excl_vat


@pytest.mark.django_db
def test_get_or_create_cdr_from_session_returns_none_when_no_connector_assigned_to_session(
    mock_session, caplog
):
    caplog.set_level(logging.ERROR)
    mock_session.connector = None

    result = CdrService.get_or_create_cdr(mock_session)

    assert result is None
    assert (
        f"Not creating a CDR from Session {mock_session.uid} since no Connector is specified"
        in caplog.text
    )


@pytest.mark.django_db
def test_get_or_create_cdr_from_session_returns_existing_cdr(mock_session):
    mock_cdr = Mock()

    with patch("ocpi22.cpo.services.CdrService._get_cdr", return_value=mock_cdr):
        result = CdrService.get_or_create_cdr(mock_session)

    assert result == mock_cdr


@pytest.mark.django_db
@time_machine.travel("2023-01-01 15:00:00")
def test_get_or_create_cdr_from_session_sets_end_date_when_missing(mock_session):
    mock_session.end_date_time = None
    mock_cdr = Mock()

    with patch("ocpi22.cpo.services.CdrService._create_cdr", return_value=mock_cdr):
        result = CdrService.get_or_create_cdr(mock_session)

    assert result == mock_cdr
    assert mock_session.end_date_time == datetime(2023, 1, 1, 15, 0, 0, tzinfo=pytz.UTC)


@pytest.mark.django_db
def test_get_or_create_cdr_from_session_logs_warning_when_no_total_cost(
    mock_session, caplog
):
    caplog.set_level(logging.ERROR)
    mock_session.total_cost_excl_vat = None
    CdrService.get_or_create_cdr(mock_session)

    assert f"Session {mock_session} has no total cost" in caplog.text


@pytest.mark.django_db
def test_get_or_create_cdr_from_session_sends_updates_after_creation(mock_session):
    mock_cdr = Mock()

    with (
        patch("ocpi22.cpo.services.CdrService._get_cdr", return_value=None),
        patch("ocpi22.cpo.services.CdrService._create_cdr", return_value=mock_cdr),
    ):
        result = CdrService.get_or_create_cdr(mock_session)

    assert result == mock_cdr
    mock_cdr.send_updates.assert_called_once()
