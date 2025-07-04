import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import pytz
import responses
from django.conf import settings
from responses import matchers

from integrations.hubject.ocpi_to_oicp_converter import (
    convert_to_charging_notification_start,
    convert_to_charging_notification_progress,
    convert_to_charging_notification_end,
)
from integrations.hubject.schemas import ChargingNotificationType
from integrations.hubject.services import HubjectService
from ocpi22.models.session import Session
from ocpi22.tests.factories import OCPISessionFactory


@pytest.mark.django_db
def test_convert_session_to_charging_notification_start_with_defaults_succeeds():
    session = OCPISessionFactory()
    notification = convert_to_charging_notification_start(session)

    assert notification.SessionID.root == session.hub_session_id
    assert notification.EvseID.root == session.evse.evse_id
    assert notification.ChargingStart == session.start_date_time
    assert notification.SessionStart == session.start_date_time
    expected_operator = f"{session.location.ocpi_master.country_code}*{session.location.ocpi_master.party_id}"
    assert notification.OperatorID.root == expected_operator
    assert (
        notification.Identification.RFIDMifareFamilyIdentification.UID.root
        == session.cdr_token.uid
    )
    assert notification.MeterValueStart == 0.0


@pytest.mark.django_db
def test_convert_session_to_charging_notification_start_with_meter_start_succeeds():
    meter_start_value = 42.5
    session = OCPISessionFactory(start_kwh=meter_start_value)
    notification = convert_to_charging_notification_start(session)

    assert notification.MeterValueStart == meter_start_value, notification


@pytest.mark.django_db
def test_convert_session_to_charging_notification_progress_defaults_succeeds():
    session = OCPISessionFactory()
    session.last_updated = session.start_date_time + timedelta(minutes=5)
    notification = convert_to_charging_notification_progress(session)

    assert notification.Type == ChargingNotificationType.Progress
    assert notification.SessionID.root == session.hub_session_id
    assert notification.EvseID.root == session.evse.evse_id
    assert notification.ChargingStart == session.start_date_time
    assert notification.EventOccurred == session.last_updated
    assert notification.ConsumedEnergyProgress == 120.0


@pytest.mark.django_db
def test_convert_session_to_charging_notification_progress_with_consumed_energy_succeeds():
    now = datetime(2000, 1, 1, 12, 0, 0, tzinfo=pytz.utc)
    session = OCPISessionFactory(start_date_time=now - timedelta(hours=1))
    session.last_updated = now
    session.stop_kwh = 12.5

    notification = convert_to_charging_notification_progress(session)

    assert notification.EventOccurred == now
    assert notification.ConsumedEnergyProgress == 12.5


@pytest.mark.django_db
def test_convert_session_to_charging_notification_progress_with_duration_only_succeeds():
    now = datetime(2000, 1, 1, 12, 0, 0, tzinfo=pytz.utc)
    start = now - timedelta(minutes=30)
    session = OCPISessionFactory(start_date_time=start, end_date_time=now)
    session.last_updated = now
    session.current_kwh = None

    notification = convert_to_charging_notification_progress(session)

    expected_ms = int((now - start).total_seconds() * 1000)
    assert notification.ChargingDuration == expected_ms, (
        type(session),
        session.total_time_float,
        session.start_date_time,
        session.end_date_time,
        now,
    )
    assert notification.ConsumedEnergyProgress == 120.0


@pytest.mark.django_db
def test_convert_session_to_charging_notification_end_basic_mapping_succeeds():
    now = datetime(2000, 1, 1, 12, 0, 0, tzinfo=pytz.utc)
    start = now - timedelta(hours=2)
    end = now
    start_kwh = 10.0
    stop_kwh = 25.0

    session = OCPISessionFactory(
        start_date_time=start,
        end_date_time=end,
        start_kwh=start_kwh,
        stop_kwh=stop_kwh,
    )
    notification = convert_to_charging_notification_end(session)

    assert notification.Type == ChargingNotificationType.End
    assert notification.SessionID.root == session.hub_session_id
    assert notification.EvseID.root == session.evse.evse_id
    assert notification.ChargingStart == start
    assert notification.ChargingEnd == end
    assert notification.SessionStart == start
    assert notification.SessionEnd == end
    assert notification.MeterValueStart == start_kwh
    assert notification.MeterValueEnd == stop_kwh
    assert notification.ConsumedEnergy == pytest.approx(stop_kwh - start_kwh)


@pytest.mark.django_db
def test_convert_session_to_charging_notification_end_negative_meter_raises_value_error():
    now = datetime(2000, 1, 1, 12, 0, 0, tzinfo=pytz.utc)
    start = now - timedelta(minutes=30)
    end = now

    session = OCPISessionFactory(start_date_time=start, end_date_time=end)
    session.start_kwh = -5.0
    session.stop_kwh = 1.0

    with pytest.raises(ValueError):
        convert_to_charging_notification_end(session)


@pytest.fixture
def charge_notification_payload():
    def generate_payload(session: Session, notification_type: ChargingNotificationType):
        payload = HubjectService.create_charging_notification_payload(
            session, notification_type
        )
        return payload.model_dump(mode="json")

    return generate_payload


@responses.activate
@pytest.mark.django_db
@pytest.mark.parametrize(
    "notification_type",
    [
        ChargingNotificationType.Start,
        ChargingNotificationType.End,
        ChargingNotificationType.Progress,
    ],
)
def test_send_updates_calls_correct_method(
    notification_type, charge_notification_payload
):
    session = OCPISessionFactory()
    payload = charge_notification_payload(session, notification_type)
    responses.add(
        responses.POST,
        f"{settings.HUBJECT_URL}notificationmgmt/v11/charging-notifications",
        status=200,
        match=[matchers.json_params_matcher(payload)],
    )

    HubjectService.send_update(session, notification_type)  # noqa
    response = responses.calls[0].response
    assert (
        response.request.url
        == f"{settings.HUBJECT_URL}notificationmgmt/v11/charging-notifications"
    )
    assert response.status_code == 200
    assert json.loads(response.request.body)["Type"] == notification_type.value


@responses.activate
@pytest.mark.django_db
@pytest.mark.parametrize(
    "update_type",
    [
        ChargingNotificationType.Start,
        ChargingNotificationType.End,
        ChargingNotificationType.Progress,
    ],
)
def test_route_through_oicp_true_invokes_send_update(hubject_credentials, update_type):
    session = OCPISessionFactory(credentials=hubject_credentials)
    with patch.object(HubjectService, "send_update") as mock_send:
        result = session.send_updates(
            update_type=update_type,
        )
    mock_send.assert_called_once_with(session=session, update_type=update_type)
    assert result is None
