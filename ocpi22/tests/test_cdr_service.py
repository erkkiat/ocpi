import logging

import pytest
import pytz
from datetime import datetime
from unittest.mock import Mock, patch

import time_machine
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError
from django.test import override_settings
from rest_framework.exceptions import ValidationError

from ocpi22.models.cdr import Cdr
from ocpi22.models.session import ChargingPeriod, ChargingPeriodSerializer
from ocpi22.cpo.services import CdrService
from ocpi22.tests.factories import (
    ChargingPeriodFactory,
    OCPISessionFactory,
    TariffFactory,
    DefaultTariffsFactory,
    CdrTokenFactory,
    CredentialsFactory,
    CredentialsRoleFactory,
)
import orjson
from json_encoders import serialize_datetime_and_enum_to_string
from ocpi22.ocpi.serializers import CdrSerializer
from webhooks.choices import WebhookType
from webhooks.factories import WebhookInactiveFactory, WebhookInvoicingFactory
from webhooks.models import WebhookEvent, WebhookEventType, WebhookEventStatus


@pytest.fixture
def mock_session():
    session = OCPISessionFactory(cdr_token=CdrTokenFactory())
    return session


@pytest.fixture
def expected_charging_periods():
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
    mock_session, expected_charging_periods
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
    assert result == expected_charging_periods


@pytest.mark.django_db
def test_get_charging_periods_creates_charging_periods_when_session_has_no_charging_periods(
    mock_session, caplog
):
    caplog.set_level(logging.WARNING)

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
    charging_periods = ChargingPeriodSerializer(
        [ChargingPeriodFactory(tariff=tariff1), ChargingPeriodFactory(tariff=tariff2)],
        many=True,
    ).data

    result = CdrService._get_cdr_tariffs(charging_periods, "IEC_62196_T2")

    assert result == [tariff1, tariff2]


@pytest.mark.django_db
def test_get_cdr_tariffs_raises_does_not_exists_error_when_nonexistent_tariffs(caplog):
    caplog.set_level(logging.WARNING)
    tariff1 = TariffFactory(uid="CP1")
    tariff2 = TariffFactory(uid="CP2")
    charging_periods = ChargingPeriodSerializer(
        [ChargingPeriodFactory(tariff=tariff1), ChargingPeriodFactory(tariff=tariff2)],
        many=True,
    ).data

    # Change UID after creating the charging periods json.
    # This is not possible to happen irl (because of immutableTariffs) unless there is something wrong with the database.
    tariff2.uid = "NonExistentTariff"
    tariff2.save()

    standard = "IEC_62196_T2"

    with pytest.raises(
        ObjectDoesNotExist, match="Tariff with UID CP2 doesn't exist in the database"
    ):
        CdrService._get_cdr_tariffs(charging_periods, standard)


@pytest.mark.django_db
def test_get_cdr_tariffs_uses_default_tariffs_when_no_tariffs_found():
    charging_periods = ChargingPeriodSerializer(
        [ChargingPeriodFactory(tariff=None)], many=True
    ).data

    standard = "IEC_62196_T2"
    tariff = TariffFactory(uid="DefaultTariff")
    DefaultTariffsFactory(standard=standard, tariffs=[tariff])

    result = CdrService._get_cdr_tariffs(charging_periods, standard)

    assert result[0] == tariff


@pytest.mark.django_db
def test_get_cdr_tariffs_raises_validation_error_when_duplicate_tariffs_exist_in_database():
    tariff1 = TariffFactory(uid="CP1")
    tariff2 = TariffFactory(uid="CP1")
    charging_periods = ChargingPeriodSerializer(
        [ChargingPeriodFactory(tariff=tariff1), ChargingPeriodFactory(tariff=tariff2)],
        many=True,
    ).data

    with pytest.raises(ValidationError):
        CdrService._get_cdr_tariffs(charging_periods, "IEC_62196_T2")


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
    caplog.set_level(logging.WARNING)
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


@pytest.mark.django_db
@override_settings(ENABLE_HUBJECT=True)
def test_get_or_create_cdr_from_session_sends_hubject_eroaming_charge_detail_record(
    mock_session,
):
    mock_cdr = Mock()
    mock_cdr.ocpi_master = Mock()
    mock_cdr.ocpi_master.party_str.return_value = "DE*ICE"

    role = CredentialsRoleFactory(
        credentials=CredentialsFactory(), country_code="DE", party_id="ICE"
    )
    mock_session.credentials = role.credentials

    with (
        patch("ocpi22.cpo.services.CdrService._get_cdr", return_value=None),
        patch("ocpi22.cpo.services.CdrService._create_cdr", return_value=mock_cdr),
        patch(
            "integrations.hubject.services.HubjectService.post_eroaming_charge_detail_record"
        ) as mock_eroaming_cdr,
    ):
        result = CdrService.get_or_create_cdr(mock_session)

    assert result == mock_cdr
    mock_cdr.send_updates.assert_not_called()
    mock_eroaming_cdr.assert_called_once_with(
        mock_cdr.ocpi_master.party_str(), mock_cdr
    )


def _make_cdr(session):
    tariff = TariffFactory(uid="CDR-WH-CP1")
    charging_period = ChargingPeriodFactory(
        start_date_time=datetime(2023, 1, 1, 12, 0, 0, tzinfo=pytz.UTC),
        tariff=tariff,
    )
    session.chargingperiods.set([charging_period])
    session.save()
    with patch("ocpi22.cpo.services.execute_webhook_event_task"):
        return CdrService._create_cdr(session)


@pytest.mark.django_db
class TestCdrWebhookEventCreation:
    @pytest.fixture
    def cdr(self, mock_session):
        return _make_cdr(mock_session)

    def test_create_cdr_webhook_event_returns_none_when_no_invoicing_webhook_configured(
        self, cdr
    ):
        result = CdrService._create_cdr_webhook_event(cdr)

        assert result is None

    def test_create_cdr_webhook_event_returns_none_when_invoicing_webhook_is_inactive(
        self, cdr
    ):
        WebhookInactiveFactory(type=WebhookType.INVOICING, command_type=None)

        result = CdrService._create_cdr_webhook_event(cdr)

        assert result is None

    def test_create_cdr_webhook_event_persists_event_with_cdr_created_event_type(
        self, cdr
    ):
        WebhookInvoicingFactory()

        CdrService._create_cdr_webhook_event(cdr)

        event = WebhookEvent.objects.get(event_type=WebhookEventType.CDR_CREATED)
        assert event.status == WebhookEventStatus.PENDING

    def test_create_cdr_webhook_event_persists_full_cdr_serializer_payload(self, cdr):
        WebhookInvoicingFactory()

        CdrService._create_cdr_webhook_event(cdr)

        expected_payload = orjson.loads(
            orjson.dumps(
                CdrSerializer(cdr).data,
                default=serialize_datetime_and_enum_to_string,
            )
        )
        event = WebhookEvent.objects.get(event_type=WebhookEventType.CDR_CREATED)
        assert event.payload == expected_payload

    def test_create_cdr_webhook_event_returns_persisted_event(self, cdr):
        WebhookInvoicingFactory()

        event = CdrService._create_cdr_webhook_event(cdr)

        assert event is not None
        assert event.pk is not None
        assert event.event_type == WebhookEventType.CDR_CREATED

    def test_create_cdr_webhook_event_returns_none_and_logs_error_when_event_creation_fails(
        self, cdr, caplog
    ):
        WebhookInvoicingFactory()
        caplog.set_level("ERROR", logger="ocpi22.cpo.services")

        with patch(
            "ocpi22.cpo.services.WebhookEventService.create_event",
            side_effect=Exception("DB error"),
        ):
            result = CdrService._create_cdr_webhook_event(cdr)

        assert result is None
        assert f"Failed to create CDR webhook event for cdr {cdr.uid}" in caplog.text


@pytest.mark.django_db
class TestCdrWebhookDispatch:
    @pytest.fixture
    def session_with_periods(self, mock_session):
        tariff = TariffFactory(uid="CDR-DISP-CP1")
        charging_period = ChargingPeriodFactory(
            start_date_time=datetime(2023, 1, 1, 12, 0, 0, tzinfo=pytz.UTC),
            tariff=tariff,
        )
        mock_session.chargingperiods.set([charging_period])
        mock_session.save()
        return mock_session

    @patch("ocpi22.cpo.services.execute_webhook_event_task")
    def test_create_cdr_dispatches_webhook_task_after_commit_when_invoicing_webhook_configured(
        self, mock_task, session_with_periods
    ):
        WebhookInvoicingFactory()

        with patch(
            "ocpi22.cpo.services.transaction.on_commit", side_effect=lambda fn: fn()
        ):
            CdrService._create_cdr(session_with_periods)

        event = WebhookEvent.objects.get(event_type=WebhookEventType.CDR_CREATED)
        mock_task.delay.assert_called_once_with(event.id)

    @patch("ocpi22.cpo.services.execute_webhook_event_task")
    def test_create_cdr_does_not_dispatch_webhook_task_when_no_invoicing_webhook_configured(
        self, mock_task, session_with_periods
    ):
        with patch(
            "ocpi22.cpo.services.transaction.on_commit", side_effect=lambda fn: fn()
        ):
            CdrService._create_cdr(session_with_periods)

        mock_task.delay.assert_not_called()

    @patch("ocpi22.cpo.services.execute_webhook_event_task")
    @patch(
        "ocpi22.cpo.services.WebhookEventService.create_event",
        side_effect=IntegrityError("unique violation"),
    )
    def test_create_cdr_is_saved_when_webhook_event_creation_raises_db_error(
        self, mock_create_event, mock_task, session_with_periods
    ):
        WebhookInvoicingFactory()

        CdrService._create_cdr(session_with_periods)

        assert Cdr.objects.filter(session_id=session_with_periods.uid).exists()
        mock_task.delay.assert_not_called()
