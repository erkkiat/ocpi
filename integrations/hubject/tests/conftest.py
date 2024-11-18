from datetime import datetime

import pytest
import pytz

from integrations.hubject.schemas import (
    AuthenticationMode,
    Plug,
    ERoamingPushEvseData,
    ActionType,
    OperatorEvseData,
)
from ocpi22.tests.factories import (
    LocationFactory,
    ConnectorFactory,
    EvseFactory,
    CredentialsRoleFactory,
    BusinessDetailsFactory,
    EvseDataRecordFactory,
    AddressFactory,
    OperatorEvseDataFactory,
)


@pytest.fixture
def helsinki_ocpi_master():
    return CredentialsRoleFactory(
        role="CPO",
        country_code="DE",
        party_id="SMP",
        business_details=BusinessDetailsFactory(
            name="Smappee Pvt Ltd",
            website="https://www.helsinki-supercharger.com",
            logo="https://www.helsinki-supercharger.com/static/test_logo.png",
        ),
    )


@pytest.fixture
def helsinki_operator_details():
    return BusinessDetailsFactory(
        name="Helsinki Supercharger Operator",
        website="https://www.helsinki-supercharger.com",
        logo="https://www.helsinki-supercharger.com/static/test_logo.png",
    )


@pytest.fixture
def helsinki_sub_operator_details(helsinki_ocpi_master):
    return BusinessDetailsFactory(
        name="Helsinki Supercharger Sub Operator",
        website="https://www.helsinki-supercharger.com",
        logo="https://www.helsinki-supercharger.com/static/test_logo.png",
    )


@pytest.fixture
def helsinki_owner_details():
    return BusinessDetailsFactory(
        name="Smappee Pvt Ltd.",
        website="https://www.helsinki-supercharger.com",
        logo="https://www.helsinki-supercharger.com/static/test_logo.png",
    )


@pytest.fixture
def helsinki_evse(helsinki_location):
    return EvseFactory(
        evse_id="FI*ABC*E1234*5668",
        status="RESERVED",
        location=helsinki_location,
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        capabilities=["RFID_READER", "RESERVABLE"],
    )


@pytest.fixture
def helsinki_connector(helsinki_evse):
    return ConnectorFactory(
        uid="CONNECTOR_1",
        evse=helsinki_evse,
        standard="IEC_62196_T2",
        format="SOCKET",
        power_type="DC",
        max_voltage=230,
        max_amperage=16,
        max_electric_power=37,
        terms_and_conditions="https://www.helsinki-supercharger.com/terms-and-conditions",
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
    )


@pytest.fixture
def helsinki_location(
    helsinki_ocpi_master,
    helsinki_operator_details,
    helsinki_sub_operator_details,
    helsinki_owner_details,
):
    return LocationFactory(
        publish=True,
        name="Helsinki Supercharger",
        address="Mannerheimintie 1",
        city="Helsinki",
        postal_code="00100",
        state="Uusimaa",
        country="FIN",
        parking_type="ON_STREET",
        latitude=60.1695,
        longitude=24.9354,
        time_zone="Europe/Helsinki",
        ocpi_master=helsinki_ocpi_master,
        operator=helsinki_operator_details,
        suboperator=helsinki_sub_operator_details,
        owner=helsinki_owner_details,
        charging_when_closed=True,
    )


@pytest.fixture
def berlin_ocpi_master():
    return CredentialsRoleFactory(
        role="CPO",
        country_code="DE",
        party_id="SMP",
    )


@pytest.fixture
def berlin_evse_data(berlin_location):
    return EvseFactory(
        evse_id="FI*ABC*1234*C0*CT",
        status="",
        location=berlin_location,
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        capabilities=None,
    )


@pytest.fixture
def connector(berlin_evse_data):
    return ConnectorFactory(
        uid="CONNECTOR_1",
        evse=berlin_evse_data,
        standard="IEC_62196_T2",
        format="",
        power_type="",
        max_voltage=-100,
        max_amperage=16,
        max_electric_power=1400,
        terms_and_conditions="https://www.berlin-supercharger.com/terms-and-conditions",
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
    )


@pytest.fixture
def berlin_location(berlin_ocpi_master):
    return LocationFactory(
        name="Berlin Location",
        address="Ansgarstr. 4",
        city="Wallenhorst",
        postal_code="49134",
        state="",
        country="DEU",
        latitude=9.360922,
        longitude=47.662249,
        time_zone="Europe/Berlin",
        ocpi_master=berlin_ocpi_master,
        operator=None,
        suboperator=None,
        owner=None,
        charging_when_closed=True,
    )


@pytest.fixture
def emsdetten_location(berlin_ocpi_master):
    return LocationFactory(
        name="Emsdetten Location",
        address="Südring 25",
        city="Emsdetten",
        postal_code="38170",
        state="",
        country="DEU",
        latitude=9.360922,
        longitude=47.662249,
        time_zone="Europe/Berlin",
        ocpi_master=berlin_ocpi_master,
        operator=None,
        suboperator=None,
        owner=None,
        charging_when_closed=True,
    )


@pytest.fixture
def emsdetten_evse(emsdetten_location):
    return EvseFactory(
        evse_id="FI*ABC*1234*C2*CT",
        status="",
        location=emsdetten_location,
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        capabilities=None,
    )


@pytest.fixture
def emsdetten_connector(emsdetten_evse):
    return ConnectorFactory(
        uid="CONNECTOR_2",
        evse=emsdetten_evse,
        standard="IEC_62196_T2",
        format="",
        power_type="",
        max_voltage=-100,
        max_amperage=16,
        max_electric_power=1400,
        terms_and_conditions="https://www.berlin-supercharger.com/terms-and-conditions",
        last_updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        updated=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        created=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
    )


@pytest.fixture
def emsdetten_op_evse_data(emsdetten_evse):
    return OperatorEvseDataFactory.build(
        OperatorID="DE*SMP",
        OperatorName="Smappee Operator",
        EvseDataRecord=[emsdetten_evse],
    )


@pytest.fixture
def berlin_op_evse_data(berlin_evse_data):
    return OperatorEvseDataFactory.build(
        OperatorID="DE*SMP",
        OperatorName="Smappee Operator",
        EvseDataRecord=[berlin_evse_data],
    )


@pytest.fixture
def berlin_evse_data_record():
    return EvseDataRecordFactory(
        lastUpdate=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        EvseID="FI*ABC*E1234*C0*CT",
        Address=AddressFactory(
            Country="DEU",
            City="Wallenhorst",
            Street="Evolis",
            PostalCode="49134",
            HouseNum="4",
            ParkingFacility=True,
            TimeZone="UTC+01:00",
        ),
        Plugs=[Plug.Type_2_Outlet],
        CalibrationLawDataAvailability="Local",
        AuthenticationModes=[AuthenticationMode.NFC_RFID_Classic],
        PaymentOptions=["Direct"],
        ValueAddedServices=["Reservation"],
        AccessibilityLocation="OnStreet",
        HotlinePhoneNumber="+3256380211",
        IsHubjectCompatible=False,
        DynamicInfoAvailable="false",
    )


@pytest.fixture
def emsdetten_evse_data_records():
    return EvseDataRecordFactory(
        lastUpdate=pytz.utc.localize(datetime(2024, 9, 22, 17, 32, 8, 599540)),
        EvseID="FI*ABC*E1234*C0*CT",
        Address=AddressFactory(
            Country="DEU",
            City="Harelbeke",
            Street="Südring",
            PostalCode="38170",
            HouseNum="25",
            Floor="1",
            Region="Flanders",
            ParkingFacility=True,
            ParkingSpot="Parking Spot1",
            TimeZone="UTC+01:00",
        ),
        Plugs=[Plug.Type_2_Outlet],
        CalibrationLawDataAvailability="Local",
        AuthenticationModes=[AuthenticationMode.NFC_RFID_Classic],
        PaymentOptions=["Direct"],
        ValueAddedServices=["Reservation"],
        AccessibilityLocation="OnStreet",
        HotlinePhoneNumber="+3256380211",
        IsHubjectCompatible=False,
        DynamicInfoAvailable="false",
    )


@pytest.fixture
def evse_full_load_payload(berlin_op_evse_data, emsdetten_op_evse_data):
    return ERoamingPushEvseData(
        ActionType=ActionType.fullLoad,
        OperatorEvseData=OperatorEvseData(
            OperatorID=berlin_op_evse_data.OperatorID,
            OperatorName=berlin_op_evse_data.OperatorName,
            EvseDataRecord=[berlin_op_evse_data, emsdetten_op_evse_data],
        ),
    )


@pytest.fixture
def hubject_successful_response():
    return {
        "Result": "true",
        "StatusCode": {
            "Code": "000",
            "Description": "null",
            "AdditionalInfo": "null",
        },
        "SessionID": "null",
        "CPOPartnerSessionID": "null",
        "EMPPartnerSessionID": "null",
    }


@pytest.fixture
def hubject_unsuccessful_response():
    return {
        "message": "Error parsing/validating JSON.",
        "validationErrors": [
            {
                "fieldReference": "operatorEvseData.evseDataRecord[0].valueAddedServices",
                "errorMessage": "must not be empty",
            }
        ],
    }
