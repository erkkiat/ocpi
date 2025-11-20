import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import pytz
import responses
from django.conf import settings
from pydantic import ValidationError
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
from util import hours_to_milliseconds


@pytest.mark.django_db
def test_convert_session_to_charging_notification_start_with_defaults_succeeds():
    session = OCPISessionFactory()
    notification = convert_to_charging_notification_start(session)

    assert notification.session_id.root == session.hub_session_id
    assert notification.evse_id.root == session.evse.evse_id
    assert notification.charging_start == session.start_date_time
    assert notification.session_start == session.start_date_time
    expected_operator = f"{session.location.ocpi_master.country_code}*{session.location.ocpi_master.party_id}"
    assert notification.operator_id.root == expected_operator
    assert (
        notification.identification.RFIDMifareFamilyIdentification.UID.root
        == session.cdr_token.uid
    )
    assert notification.meter_value_start == 0.0


@pytest.mark.django_db
def test_convert_session_to_charging_notification_start_with_meter_start_succeeds():
    meter_start_value = 42.5
    session = OCPISessionFactory(start_kwh=meter_start_value)
    notification = convert_to_charging_notification_start(session)

    assert notification.meter_value_start == meter_start_value, notification


@pytest.mark.django_db
def test_convert_session_to_charging_notification_progress_defaults_succeeds():
    session = OCPISessionFactory()
    session.last_updated = session.start_date_time + timedelta(minutes=5)
    notification = convert_to_charging_notification_progress(session)

    assert notification.type == ChargingNotificationType.Progress
    assert notification.session_id.root == session.hub_session_id
    assert notification.evse_id.root == session.evse.evse_id
    assert notification.charging_start == session.start_date_time
    assert notification.event_occurred == session.last_updated
    assert notification.consumed_energy_progress == 120.0


@pytest.mark.django_db
def test_convert_session_to_charging_notification_progress_with_consumed_energy_succeeds():
    now = datetime(2000, 1, 1, 12, 0, 0, tzinfo=pytz.utc)
    session = OCPISessionFactory(start_date_time=now - timedelta(hours=1))
    session.last_updated = now
    session.stop_kwh = 12.5

    notification = convert_to_charging_notification_progress(session)

    assert notification.event_occurred == now
    assert notification.consumed_energy_progress == 12.5


@pytest.mark.django_db
def test_convert_session_to_charging_notification_progress_with_duration_only_succeeds():
    now = datetime(2000, 1, 1, 12, 0, 0, tzinfo=pytz.utc)
    start = now - timedelta(minutes=30)
    session = OCPISessionFactory(start_date_time=start, end_date_time=now)
    session.last_updated = now
    session.current_kwh = None

    notification = convert_to_charging_notification_progress(session)

    expected_ms = int((now - start).total_seconds() * 1000)
    assert notification.charging_duration == expected_ms, (
        type(session),
        session.total_time_float,
        session.start_date_time,
        session.end_date_time,
        now,
    )
    assert notification.consumed_energy_progress == 120.0


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

    assert notification.type == ChargingNotificationType.End
    assert notification.session_id.root == session.hub_session_id
    assert notification.evse_id.root == session.evse.evse_id
    assert notification.charging_start == start
    assert notification.charging_end == end
    assert notification.session_start == start
    assert notification.session_end == end
    assert notification.meter_value_start == start_kwh
    assert notification.meter_value_end == stop_kwh
    assert notification.consumed_energy == pytest.approx(stop_kwh - start_kwh)


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


@pytest.mark.django_db
def test_create_charging_notification_payload_start_successfully():
    session = OCPISessionFactory()
    expected_payload = {
        "cpo_partner_session_id": None,
        "charging_start": "2021-01-01T10:00:00Z",
        "emp_partner_session_id": None,
        "evse_id": session.evse.evse_id,
        "identification": {
            "RFIDMifareFamilyIdentification": {"UID": "DEADC0DE"},
            "RemoteIdentification": None,
            "QRCodeIdentification": None,
            "RFIDIdentification": None,
            "PlugAndChargeIdentification": None,
        },
        "meter_value_start": 0.0,
        "operator_id": "FI*CPO",
        "partner_product_id": None,
        "session_id": session.hub_session_id,
        "session_start": "2021-01-01T10:00:00Z",
        "type": "Start",
    }
    payload = HubjectService.create_charging_notification_payload(
        session, ChargingNotificationType.Start
    )
    assert payload.model_dump(mode="json") == expected_payload


@pytest.mark.django_db
def test_create_charging_notification_payload_start_with_invalid_charging_start_raises_value_error():
    session = OCPISessionFactory()
    session.start_date_time = None
    with pytest.raises(ValidationError):
        HubjectService.create_charging_notification_payload(
            session, ChargingNotificationType.Start
        )


@pytest.mark.django_db
def test_create_charging_notification_payload_progress_successfully():
    session = OCPISessionFactory()
    expected_payload = {
        "cpo_partner_session_id": None,
        "charging_start": "2021-01-01T10:00:00Z",
        "emp_partner_session_id": None,
        "evse_id": session.evse.evse_id,
        "identification": {
            "RFIDMifareFamilyIdentification": {"UID": "DEADC0DE"},
            "RemoteIdentification": None,
            "QRCodeIdentification": None,
            "RFIDIdentification": None,
            "PlugAndChargeIdentification": None,
        },
        "meter_value_start": 0.0,
        "charging_duration": hours_to_milliseconds(session.total_time_float),
        "meter_value_in_between": None,
        "event_occurred": "2021-01-01T12:00:00Z",
        "consumed_energy_progress": 120.0,
        "operator_id": "FI*CPO",
        "partner_product_id": None,
        "session_id": session.hub_session_id,
        "session_start": "2021-01-01T10:00:00Z",
        "type": "Progress",
    }
    payload = HubjectService.create_charging_notification_payload(
        session, ChargingNotificationType.Progress
    )
    assert payload.model_dump(mode="json") == expected_payload


@pytest.mark.django_db
def test_create_charging_notification_payload_progress_with_invalid_charging_start_raises_value_error():
    session = OCPISessionFactory()
    session.start_date_time = datetime.now(pytz.utc) + timedelta(days=10)
    with pytest.raises(ValidationError):
        HubjectService.create_charging_notification_payload(
            session, ChargingNotificationType.Progress
        )


@pytest.mark.django_db
def test_create_charging_notification_payload_progress_with_invalid_event_occurred_raises_value_error():
    session = OCPISessionFactory()
    session.last_updated = None
    with pytest.raises(ValidationError):
        HubjectService.create_charging_notification_payload(
            session, ChargingNotificationType.Progress
        )


@pytest.mark.django_db
def test_create_charging_notification_payload_end_with_invalid_charging_end_raises_value_error():
    session = OCPISessionFactory()
    session.end_date_time = None
    with pytest.raises(ValidationError):
        HubjectService.create_charging_notification_payload(
            session, ChargingNotificationType.End
        )


@pytest.mark.django_db
def test_create_charging_notification_payload_end_successfully():
    session = OCPISessionFactory()
    expected_payload = {
        "cpo_partner_session_id": None,
        "charging_start": "2021-01-01T10:00:00Z",
        "emp_partner_session_id": None,
        "evse_id": session.evse.evse_id,
        "identification": {
            "RFIDMifareFamilyIdentification": {"UID": "DEADC0DE"},
            "RemoteIdentification": None,
            "QRCodeIdentification": None,
            "RFIDIdentification": None,
            "PlugAndChargeIdentification": None,
        },
        "meter_value_start": 0.0,
        "charging_end": "2021-01-01T12:00:00Z",
        "session_end": "2021-01-01T12:00:00Z",
        "meter_value_end": 120.0,
        "consumed_energy": 120.0,
        "operator_id": "FI*CPO",
        "partner_product_id": None,
        "penalty_time_start": None,
        "meter_value_in_between": None,
        "session_id": session.hub_session_id,
        "session_start": "2021-01-01T10:00:00Z",
        "type": "End",
    }
    payload = HubjectService.create_charging_notification_payload(
        session, ChargingNotificationType.End
    )
    assert payload.model_dump(mode="json") == expected_payload


@pytest.mark.django_db
def test_invalid_notification_type_raises_value_error():
    with pytest.raises(
        ValueError, match="Unsupported session notification type: InvalidType"
    ):
        HubjectService.create_charging_notification_payload(
            session=OCPISessionFactory(), notification_type="InvalidType"
        )


@pytest.fixture
def charge_notification_payload():
    def generate_payload(session: Session, notification_type: ChargingNotificationType):
        payload = HubjectService.create_charging_notification_payload(
            session, notification_type
        )
        return payload.model_dump(mode="json", by_alias=True)

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
    assert len(responses.calls) == 1
    response = responses.calls[0].response
    assert (
        response.request.url
        == f"{settings.HUBJECT_URL}notificationmgmt/v11/charging-notifications"
    )
    assert response.status_code == 200
    assert json.loads(response.request.body)["Type"] == notification_type.value


@pytest.mark.django_db
def test_send_progress_update_does_not_send_update_for_kwh_zero():
    session = OCPISessionFactory(start_kwh=0.0, stop_kwh=0.0)
    with patch(
        "integrations.hubject.services.HubjectService.post_charging_notification"
    ) as mock_post:
        HubjectService.send_update(session, ChargingNotificationType.Progress)

    assert not mock_post.called


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
def test_route_through_oicp_true_invokes_send_update(
    hubject_credentials, notification_type
):
    session = OCPISessionFactory(credentials=hubject_credentials)
    with patch.object(HubjectService, "send_update") as mock_send:
        result = session.send_updates(
            update_type=notification_type,
        )
    mock_send.assert_called_once_with(
        session=session, notification_type=notification_type
    )
    assert result is None
