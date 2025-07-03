import json
from datetime import datetime, timedelta

import pytest
import pytz
import responses
from django.conf import settings

from integrations.hubject.ocpi_to_oicp_converter import (
    convert_ocpi_session_to_oicp_charging_notification_start,
    convert_ocpi_session_to_oicp_charging_notification_progress,
    convert_ocpi_session_to_oicp_charging_notification_end,
)
from integrations.hubject.schemas import ChargingNotificationType
from integrations.hubject.services import HubjectService
from ocpi22.tests.factories import OCPISessionFactory


@pytest.mark.django_db
def test_convert_session_to_charging_notification_start_with_defaults_succeeds():
    session = OCPISessionFactory()
    notification = convert_ocpi_session_to_oicp_charging_notification_start(session)

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
    notification = convert_ocpi_session_to_oicp_charging_notification_start(session)

    assert notification.MeterValueStart == meter_start_value, notification


@pytest.mark.django_db
def test_convert_session_to_charging_notification_progress_defaults_succeeds():
    session = OCPISessionFactory()
    session.last_updated = session.start_date_time + timedelta(minutes=5)
    notification = convert_ocpi_session_to_oicp_charging_notification_progress(session)

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

    notification = convert_ocpi_session_to_oicp_charging_notification_progress(session)

    assert notification.EventOccurred == now
    assert notification.ConsumedEnergyProgress == 12.5


@pytest.mark.django_db
def test_convert_session_to_charging_notification_progress_with_duration_only_succeeds():
    now = datetime(2000, 1, 1, 12, 0, 0, tzinfo=pytz.utc)
    start = now - timedelta(minutes=30)
    session = OCPISessionFactory(start_date_time=start, end_date_time=now)
    session.last_updated = now
    session.current_kwh = None

    notification = convert_ocpi_session_to_oicp_charging_notification_progress(session)

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
    notification = convert_ocpi_session_to_oicp_charging_notification_end(session)

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
        convert_ocpi_session_to_oicp_charging_notification_end(session)


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
def test_send_updates_calls_correct_method(update_type):
    def session_evse_matcher(
        session_id,
        evse_id,
        upd_type,
        identification,
        charging_start,
        session_start,
        meter_value_start,
        operator_id,
        cpo_partner_session_id,
        emp_partner_session_id,
        partner_product_id,
    ):
        def _matcher(request):
            payload = json.loads(request.body)
            if (
                payload.get("SessionID") != session_id
                or payload.get("EvseID") != evse_id
            ):
                return False, (
                    f"Expected SessionID={session_id}, EvseID={evse_id}; "
                    f"got SessionID={payload.get('SessionID')}, EvseID={payload.get('EvseID')}"
                )
            if payload.get("Type") != upd_type:
                return (
                    False,
                    f"Expected Type={upd_type}; got Type={payload.get('Type')}",
                )
            assert (
                payload.get("Identification", {})
                .get("RFIDMifareFamilyIdentification", {})
                .get("UID")
                == identification
            ), f"Expected UID={identification}; got {payload.get('Identification', {}).get('RFIDMifareFamilyIdentification', {}).get('UID')}"
            assert (
                payload.get("ChargingStart") == charging_start
            ), f"Expected ChargingStart={charging_start}; got {payload.get('ChargingStart')}"
            assert (
                payload.get("SessionStart") == session_start
            ), f"Expected SessionStart={session_start}; got {payload.get('SessionStart')}"
            assert (
                payload.get("MeterValueStart") == meter_value_start
            ), f"Expected MeterValueStart={meter_value_start}; got {payload.get('MeterValueStart')}"
            assert (
                payload.get("OperatorID") == operator_id
            ), f"Expected OperatorID={operator_id}; got {payload.get('OperatorID')}"
            assert (
                payload.get("CPOPartnerSessionID") == cpo_partner_session_id
            ), f"Expected CPOPartnerSessionID={cpo_partner_session_id}; got {payload.get('CPOPartnerSessionID')}"
            assert (
                payload.get("EMPPartnerSessionID") == emp_partner_session_id
            ), f"Expected EMPPartnerSessionID={emp_partner_session_id}; got {payload.get('EMPPartnerSessionID')}"
            assert (
                payload.get("PartnerProductID") == partner_product_id
            ), f"Expected PartnerProductID={partner_product_id}; got {payload.get('PartnerProductID')}"
            return True, None

        return _matcher

    ocpi_session = OCPISessionFactory()
    start_date_time = ocpi_session.start_date_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    responses.add(
        responses.POST,
        f"{settings.HUBJECT_URL}notificationmgmt/v11/charging-notifications",
        json={},
        status=200,
        match=[
            session_evse_matcher(
                session_id=ocpi_session.hub_session_id,
                evse_id=ocpi_session.evse.evse_id,
                upd_type=update_type.value,
                identification=ocpi_session.cdr_token.uid,
                charging_start=start_date_time,
                session_start=start_date_time,
                meter_value_start=ocpi_session.start_kwh or 0.0,
                operator_id=f"{ocpi_session.location.ocpi_master.country_code}*{ocpi_session.location.ocpi_master.party_id}",
                cpo_partner_session_id=None,
                emp_partner_session_id=None,
                partner_product_id=None,
            ),
        ],
    )

    response = HubjectService.send_update(ocpi_session, update_type)
    assert response.status_code == 200, response.content
