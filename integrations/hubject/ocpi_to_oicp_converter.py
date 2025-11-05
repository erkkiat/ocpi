import logging

from integrations.hubject.schemas import (
    ERoamingChargingNotificationStart,
    SessionID,
    EvseID,
    OperatorID,
    ERoamingChargingNotificationProgress,
    ERoamingChargingNotificationEnd,
)
from typing import TYPE_CHECKING

from integrations.solid_to_hubject_converter import SolidToHubjectConverter
from util import hours_to_milliseconds

if TYPE_CHECKING:
    from ocpi22.models.session import Session

logger = logging.getLogger(__name__)


def convert_to_charging_notification_base_data(ocpi_session: "Session") -> dict:
    ocpi_master = ocpi_session.location.ocpi_master
    try:
        identification = SolidToHubjectConverter.get_identification(
            session=ocpi_session
        )
    except Exception:
        logger.exception(exc_info=True)
        raise
    return {
        "session_id": SessionID(root=ocpi_session.hub_session_id),
        "evse_id": EvseID(root=ocpi_session.evse.evse_id),
        "charging_start": ocpi_session.start_date_time,
        "session_start": ocpi_session.start_date_time,
        "operator_id": OperatorID(
            root=f"{ocpi_master.country_code}*{ocpi_master.party_id}"
        ),
        "identification": identification,
        "meter_value_start": ocpi_session.start_kwh or 0.0,
    }


def convert_to_charging_notification_start(
    ocpi_session: "Session",
) -> ERoamingChargingNotificationStart:
    data = convert_to_charging_notification_base_data(ocpi_session)
    return ERoamingChargingNotificationStart(**data)


def convert_to_charging_notification_progress(
    ocpi_session: "Session",
) -> ERoamingChargingNotificationProgress:
    data = convert_to_charging_notification_base_data(ocpi_session)
    return ERoamingChargingNotificationProgress(
        charging_duration=hours_to_milliseconds(ocpi_session.total_time_float),
        event_occurred=ocpi_session.last_updated,
        consumed_energy_progress=ocpi_session.kwh or 0.0,
        **data,
    )


def convert_to_charging_notification_end(
    ocpi_session: "Session",
) -> ERoamingChargingNotificationEnd:
    data = convert_to_charging_notification_base_data(ocpi_session)
    return ERoamingChargingNotificationEnd(
        charging_end=ocpi_session.end_date_time,
        session_end=ocpi_session.end_date_time,
        meter_value_end=ocpi_session.stop_kwh,
        consumed_energy=ocpi_session.kwh or 0.0,
        **data,
    )
