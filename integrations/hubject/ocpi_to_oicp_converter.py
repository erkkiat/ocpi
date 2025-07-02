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


def convert_ocpi_session_to_oicp_charging_notification_base_data(ocpi_session) -> dict:
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


def convert_ocpi_session_to_oicp_charging_notification_start(
    ocpi_session,
) -> ERoamingChargingNotificationStart:
    data = convert_ocpi_session_to_oicp_charging_notification_base_data(ocpi_session)
    return ERoamingChargingNotificationStart(**data)


def hours_to_milliseconds(total_time_float: float) -> int:
    return int(total_time_float * 3600 * 1000)


def convert_ocpi_session_to_oicp_charging_notification_progress(
    ocpi_session,
) -> ERoamingChargingNotificationProgress:
    data = convert_ocpi_session_to_oicp_charging_notification_base_data(ocpi_session)
    return ERoamingChargingNotificationProgress(
        ChargingDuration=hours_to_milliseconds(ocpi_session.total_time_float),
        EventOccurred=ocpi_session.last_updated,
        ConsumedEnergyProgress=ocpi_session.kwh or 0.0,
        **data,
    )


def convert_ocpi_session_to_oicp_charging_notification_end(
    ocpi_session,
) -> ERoamingChargingNotificationEnd:
    data = convert_ocpi_session_to_oicp_charging_notification_base_data(ocpi_session)
    return ERoamingChargingNotificationEnd(
        ChargingEnd=ocpi_session.end_date_time,
        SessionEnd=ocpi_session.end_date_time,
        MeterValueEnd=ocpi_session.stop_kwh,
        ConsumedEnergy=ocpi_session.kwh or 0.0,
        **data,
    )
