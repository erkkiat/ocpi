from integrations.hubject.schemas import (
    ERoamingChargingNotificationStart,
    SessionID,
    EvseID,
    OperatorID,
    IdentificationClass,
    RFIDMifareFamilyIdentificationClass,
    UID,
    ERoamingChargingNotificationProgress,
    ERoamingChargingNotificationEnd,
)
from typing import TYPE_CHECKING

from util import hours_to_milliseconds

if TYPE_CHECKING:
    from ocpi22.models.session import Session


def convert_to_charging_notification_base_data(ocpi_session: "Session") -> dict:
    ocpi_master = ocpi_session.location.ocpi_master
    return {
        "SessionID": SessionID(root=ocpi_session.hub_session_id),
        "EvseID": EvseID(root=ocpi_session.evse.evse_id),
        "ChargingStart": ocpi_session.start_date_time,
        "SessionStart": ocpi_session.start_date_time,
        "OperatorID": OperatorID(
            root=f"{ocpi_master.country_code}*{ocpi_master.party_id}"
        ),
        "Identification": IdentificationClass(
            RFIDMifareFamilyIdentification=RFIDMifareFamilyIdentificationClass(
                UID=UID(root=ocpi_session.cdr_token.uid)
            )
        ),
        "MeterValueStart": ocpi_session.start_kwh or 0.0,
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
        ChargingDuration=hours_to_milliseconds(ocpi_session.total_time_float),
        EventOccurred=ocpi_session.last_updated,
        ConsumedEnergyProgress=ocpi_session.kwh or 0.0,
        **data,
    )


def convert_to_charging_notification_end(
    ocpi_session: "Session",
) -> ERoamingChargingNotificationEnd:
    data = convert_to_charging_notification_base_data(ocpi_session)
    return ERoamingChargingNotificationEnd(
        ChargingEnd=ocpi_session.end_date_time,
        SessionEnd=ocpi_session.end_date_time,
        MeterValueEnd=ocpi_session.stop_kwh,
        ConsumedEnergy=ocpi_session.kwh or 0.0,
        **data,
    )
