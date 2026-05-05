from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
import pytz
import time_machine

from ocpi22.cpo.session_service import SessionService
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.routing import find_route
from ocpi22.tests.factories import (
    CdrTokenFactory,
    CredentialsRoleFactory,
    OCPISessionFactory,
    ConnectorFactory,
    LocationFactory,
    EvseFactory,
    TariffFactory,
    TokenFactory,
)
from ocpi22.tokens.auth import _authorize_token
from ocpi22.tokens.dataclasses import TokenDto


@pytest.mark.django_db
class TestSessionServiceUpdateMeterValues:
    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_sets_start_kwh_when_zero(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=0.0, stop_kwh=0.0
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        service.update_meter_values(
            session=session, timestamp=timestamp, kwh=10.5, soc=50.0, power=7.4
        )

        session.refresh_from_db()
        assert session.start_kwh == 10.5
        assert session.stop_kwh == 10.5

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_does_not_overwrite_start_kwh_when_nonzero(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=5.0, stop_kwh=5.0
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        service.update_meter_values(
            session=session, timestamp=timestamp, kwh=15.5, soc=75.0, power=7.4
        )

        session.refresh_from_db()
        assert session.start_kwh == 5.0
        assert session.stop_kwh == 15.5

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_updates_stop_kwh(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=10.0, stop_kwh=12.0
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        service.update_meter_values(
            session=session, timestamp=timestamp, kwh=20.5, soc=85.0, power=7.4
        )

        session.refresh_from_db()
        assert session.stop_kwh == 20.5

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_calls_calculate_price(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=10.0, stop_kwh=12.0
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        with patch.object(session, "calculate_price") as mock_calculate_price:
            service.update_meter_values(
                session=session, timestamp=timestamp, kwh=20.5, soc=85.0, power=7.4
            )

        mock_calculate_price.assert_called_once()

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_calls_update_last_updated(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=10.0, stop_kwh=12.0
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        with patch.object(session, "update_last_updated") as mock_update_last_updated:
            service.update_meter_values(
                session=session, timestamp=timestamp, kwh=20.5, soc=85.0, power=7.4
            )

        mock_update_last_updated.assert_called_once()

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_calls_update_charging_periods_with_kwh_delta(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=10.0, stop_kwh=12.0
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        with patch.object(
            session, "update_charging_periods"
        ) as mock_update_charging_periods:
            service.update_meter_values(
                session=session, timestamp=timestamp, kwh=20.5, soc=85.0, power=7.4
            )

        mock_update_charging_periods.assert_called_once_with(10.5, 85.0, 7.4, timestamp)

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_calls_update_charging_periods_with_none_soc_and_power(
        self,
    ):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=5.0, stop_kwh=8.0
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        with patch.object(
            session, "update_charging_periods"
        ) as mock_update_charging_periods:
            service.update_meter_values(
                session=session, timestamp=timestamp, kwh=15.0, soc=None, power=None
            )

        mock_update_charging_periods.assert_called_once_with(
            10.0, None, None, timestamp
        )

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_saves_session_with_correct_fields(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=10.0, stop_kwh=12.0
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        with patch.object(session, "save") as mock_save:
            service.update_meter_values(
                session=session, timestamp=timestamp, kwh=20.5, soc=85.0, power=7.4
            )

        assert mock_save.call_count >= 1
        mock_save.assert_any_call(
            update_fields=[
                "start_kwh",
                "stop_kwh",
                "total_cost_incl_vat",
                "total_cost_excl_vat",
                "last_updated",
            ]
        )

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_updates_cost_fields_when_tariff_exists(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector,
            status=Session.ACTIVE,
            start_kwh=10.0,
            stop_kwh=12.0,
            total_cost_incl_vat=1.0,
            total_cost_excl_vat=0.9,
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        service.update_meter_values(
            session=session, timestamp=timestamp, kwh=20.5, soc=85.0, power=7.4
        )

        session.refresh_from_db()
        assert session.total_cost_incl_vat is not None
        assert session.total_cost_excl_vat is not None

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_calculates_correct_kwh_delta_for_charging_periods(
        self,
    ):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=15.5, stop_kwh=20.0
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        service.update_meter_values(
            session=session, timestamp=timestamp, kwh=35.25, soc=90.0, power=11.0
        )

        session.refresh_from_db()
        charging_period = session.chargingperiods.first()
        energy_dimension = charging_period.dimensions.filter(type="ENERGY").first()
        assert energy_dimension.volume == Decimal("19.75")

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_handles_zero_start_kwh_and_first_update(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=0.0, stop_kwh=0.0
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        service.update_meter_values(
            session=session, timestamp=timestamp, kwh=8.5, soc=40.0, power=7.2
        )

        session.refresh_from_db()
        assert session.start_kwh == 8.5
        assert session.stop_kwh == 8.5
        charging_period = session.chargingperiods.first()
        assert charging_period is not None
        energy_dimension = charging_period.dimensions.filter(type="ENERGY").first()
        assert energy_dimension is None or energy_dimension.volume == Decimal("0.0000")

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_updates_last_updated_timestamp(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        old_timestamp = datetime(2025, 1, 14, 10, 30, 0, tzinfo=pytz.utc)
        session = OCPISessionFactory(
            connector=connector,
            status=Session.ACTIVE,
            start_kwh=10.0,
            stop_kwh=12.0,
            last_updated=old_timestamp,
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        service.update_meter_values(
            session=session, timestamp=timestamp, kwh=20.5, soc=85.0, power=7.4
        )

        session.refresh_from_db()
        assert session.last_updated > old_timestamp

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_with_only_kwh_parameter(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=5.0, stop_kwh=8.0
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        service.update_meter_values(session=session, timestamp=timestamp, kwh=18.0)

        session.refresh_from_db()
        assert session.stop_kwh == 18.0
        assert session.start_kwh == 5.0

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_with_all_optional_parameters(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=10.0, stop_kwh=15.0
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        with patch.object(
            session, "update_charging_periods"
        ) as mock_update_charging_periods:
            service.update_meter_values(
                session=session,
                timestamp=timestamp,
                kwh=25.0,
                soc=95.0,
                power=22.0,
            )

        mock_update_charging_periods.assert_called_once_with(
            15.0, 95.0, 22.0, timestamp
        )

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_with_soc_but_no_power(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=10.0, stop_kwh=15.0
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        with patch.object(
            session, "update_charging_periods"
        ) as mock_update_charging_periods:
            service.update_meter_values(
                session=session, timestamp=timestamp, kwh=25.0, soc=75.0, power=None
            )

        mock_update_charging_periods.assert_called_once_with(
            15.0, 75.0, None, timestamp
        )

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_with_power_but_no_soc(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=10.0, stop_kwh=15.0
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        with patch.object(
            session, "update_charging_periods"
        ) as mock_update_charging_periods:
            service.update_meter_values(
                session=session, timestamp=timestamp, kwh=25.0, soc=None, power=11.0
            )

        mock_update_charging_periods.assert_called_once_with(
            15.0, None, 11.0, timestamp
        )

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_with_decreasing_kwh_value(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=20.0, stop_kwh=25.0
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        service.update_meter_values(
            session=session, timestamp=timestamp, kwh=18.0, soc=50.0, power=7.4
        )

        session.refresh_from_db()
        assert session.stop_kwh == 18.0
        assert session.start_kwh == 20.0

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_with_same_kwh_as_stop_kwh(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=10.0, stop_kwh=20.0
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        with patch.object(
            session, "update_charging_periods"
        ) as mock_update_charging_periods:
            service.update_meter_values(
                session=session, timestamp=timestamp, kwh=20.0, soc=80.0, power=7.4
            )

        mock_update_charging_periods.assert_called_once_with(10.0, 80.0, 7.4, timestamp)

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_with_large_kwh_delta(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=5.0, stop_kwh=10.0
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        service.update_meter_values(
            session=session, timestamp=timestamp, kwh=155.75, soc=100.0, power=50.0
        )

        session.refresh_from_db()
        assert session.stop_kwh == 155.75
        charging_period = session.chargingperiods.first()
        energy_dimension = charging_period.dimensions.filter(type="ENERGY").first()
        assert energy_dimension.volume == Decimal("150.75")

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_with_decimal_precision(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector,
            status=Session.ACTIVE,
            start_kwh=10.123,
            stop_kwh=15.456,
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        service.update_meter_values(
            session=session, timestamp=timestamp, kwh=25.789, soc=85.5, power=7.321
        )

        session.refresh_from_db()
        assert session.stop_kwh == 25.789
        charging_period = session.chargingperiods.first()
        energy_dimension = charging_period.dimensions.filter(type="ENERGY").first()
        assert energy_dimension.volume == Decimal("15.666")

    @time_machine.travel("2025-01-15 10:30:00", tick=False)
    def test_update_meter_values_persists_all_required_fields_to_database(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        tariff = TariffFactory()
        connector = ConnectorFactory(evse=evse, tariff_ids=[tariff])
        session = OCPISessionFactory(
            connector=connector, status=Session.ACTIVE, start_kwh=10.0, stop_kwh=15.0
        )
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=pytz.utc)

        service = SessionService()
        service.update_meter_values(
            session=session, timestamp=timestamp, kwh=30.0, soc=90.0, power=11.0
        )

        session.refresh_from_db()
        assert session.start_kwh == 10.0
        assert session.stop_kwh == 30.0
        assert session.last_updated is not None
        assert session.total_cost_incl_vat is not None
        assert session.total_cost_excl_vat is not None


@pytest.fixture(autouse=True)
def clear_caches():
    _authorize_token.cache_clear()
    find_route.cache_clear()


@pytest.fixture
def always_whitelist_token():
    return TokenFactory(
        uid="ALWAYS_TOKEN",
        whitelist=Token.ALWAYS,
        ocpi_master=CredentialsRoleFactory(
            country_code="DE", party_id="TST", role="EMSP"
        ),
    )


@pytest.fixture
def always_token_dto(always_whitelist_token):
    return TokenDto(
        uid=always_whitelist_token.uid, adhoc=False, token=always_whitelist_token
    )


@pytest.mark.django_db
class TestStopAndCreateCdrClearsAuthorizeTokenCache:
    def test_stop_and_create_cdr_clears_authorize_token_cache_only_for_session_token(
        self, always_whitelist_token
    ):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        connector = ConnectorFactory(evse=evse)

        other_token = TokenFactory(
            uid="OTHER_TOKEN",
            whitelist=Token.ALWAYS,
            ocpi_master=CredentialsRoleFactory(
                country_code="DE", party_id="OTH", role="EMSP"
            ),
        )
        session_token_dto = TokenDto(
            uid=always_whitelist_token.uid, adhoc=False, token=always_whitelist_token
        )
        other_token_dto = TokenDto(uid=other_token.uid, adhoc=False, token=other_token)

        _authorize_token(
            session_token_dto, location, request=None, evse_id=evse.evse_id
        )
        _authorize_token(
            session_token_dto, location, request=None, evse_id=evse.evse_id
        )
        _authorize_token(other_token_dto, location, request=None, evse_id=evse.evse_id)
        _authorize_token(other_token_dto, location, request=None, evse_id=evse.evse_id)
        assert _authorize_token.cache_info().hits == 2

        cdr_token = CdrTokenFactory(uid=always_whitelist_token.uid)
        session = OCPISessionFactory(
            status=Session.ACTIVE,
            start_kwh=10.0,
            stop_kwh=20.0,
            cdr_token=cdr_token,
            evse=evse,
            location=location,
            connector=connector,
        )

        SessionService().stop_and_create_cdr(session, stop_kwh=30.0)

        hits_before = _authorize_token.cache_info().hits
        misses_before = _authorize_token.cache_info().misses
        _authorize_token(
            session_token_dto, location, request=None, evse_id=evse.evse_id
        )
        assert _authorize_token.cache_info().misses == misses_before + 1

        _authorize_token(other_token_dto, location, request=None, evse_id=evse.evse_id)
        assert _authorize_token.cache_info().hits == hits_before + 1
